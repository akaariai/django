from __future__ import unicode_literals

from collections import namedtuple
from fractions import Fraction

from django.db.models import signals
from django.db.models.fields import Field
from django.db.models.sql.where import Constraint, InConstraint, AND
from django.utils.functional import cached_property
from django.utils.encoding import (force_text, python_2_unicode_compatible,
        quote, unquote)
from django.utils import six


COMPOSITE_VALUE_SEPARATOR = ','
COMPOSITE_VALUE_QUOTING_CHAR = '~'


class VirtualField(Field):
    """
    Base class for field types with no direct database representation.
    """
    def __init__(self, **kwargs):
        kwargs.setdefault('serialize', False)
        kwargs.setdefault('editable', False)
        super(VirtualField, self).__init__(**kwargs)

    def db_type(self, connection):
        """
        By default no db representation, and thus also no db_type.
        """
        return None

    def contribute_to_class(self, cls, name):
        super(VirtualField, self).contribute_to_class(cls, name)

    def get_column(self):
        return None

    @cached_property
    def fields(self):
        return []

    @cached_property
    def concrete_fields(self):
        return [f
                for myfield in self.fields
                for f in myfield.concrete_fields]

    def resolve_concrete_values(self, data):
        if data is None:
            return [None] * len(self.concrete_fields)
        if len(self.concrete_fields) > 1:
            if not isinstance(data, (list, tuple)):
                raise ValueError(
                    "Can't resolve data that isn't list or tuple to values for field %s" %
                    self.name)
            elif len(data) != len(self.concrete_fields):
                raise ValueError(
                    "Invalid amount of values for field %s. Required %s, got %s." %
                    (self.name, len(self.concrete_fields), len(data)))
            return data
        else:
            return [data]

    @cached_property
    def nt(self):
        nt_name = "%s_%s" % (self.__class__.__name__, self.name)
        nt_fields = " ".join(f.name for f in self.concrete_fields)
        return get_composite_value_class(nt_name, nt_fields)

    @cached_property
    def is_multicolumn(self):
        return len(self.concrete_fields) > 1

class CompositeField(VirtualField):
    """
    Virtual field type enclosing several atomic fields into one.
    """
    prepare_after_contribute_to_class = False

    def __init__(self, *fields, **kwargs):
        self.fields = fields
        super(CompositeField, self).__init__(**kwargs)

    def clone_for_foreignkey(self, name, null, db_tablespace, counter_low,
                             counter_high, db_column, klass=None,
                             args=None, kwargs=None, fk_field=None):
        counter_low = Fraction(counter_low)
        counter_high = Fraction(counter_high)
        counter_step = (counter_high - counter_low) / (len(self.fields) + 1)
        if db_column is None:
            db_column = [None] * len(self.fields)

        result, field_names = [], []
        curr_high = counter_low
        for f, col in zip(self.fields, db_column):
            curr_low, curr_high = curr_high, curr_high + counter_step
            f_name = "%s_%s" % (fk_field.name, f.name)
            field_names.append(f_name)
            result.extend(f.clone_for_foreignkey(
                f_name, null, db_tablespace, curr_low, curr_high, col))

        result.extend(super(CompositeField, self).clone_for_foreignkey(
            name, null, db_tablespace, curr_high, counter_high, db_column,
            args=field_names, fk_field=fk_field))
        return result

    def contribute_to_class(self, cls, name):
        super(CompositeField, self).contribute_to_class(cls, name)
        setattr(cls, name, self)

        # We can process the fields only after they've been added to the
        # model class.
        def process_enclosed_fields(sender, **kwargs):
            # Resolve any field names to instances.
            new_fields = []
            for f in self.fields:
                if isinstance(f, six.string_types):
                    new_fields.append(cls._meta.get_field(f))
                else:
                    new_fields.append(f)
            self.fields = new_fields

            self.prepare()

        if cls._meta.model_prepared:
            process_enclosed_fields(cls)
        else:
            signals.class_prepared.connect(process_enclosed_fields,
                                           sender=cls, weak=False)

    def __get__(self, instance, owner):
        if instance is None:
            raise AttributeError("%s can only be retrieved via instance."
                                 % self.name)
        return self.nt._make(getattr(instance, f.attname, None) for f in self.fields)

    def __set__(self, instance, value):
        value = self.to_python(value)
        for f, val in zip([f.attname for f in self.fields], value):
            setattr(instance, f, val)

    def to_python(self, value):
        if value is None:
            value = [None] * len(self.fields)
        if isinstance(value, six.string_types):
            value = [unquote(v, escape=COMPOSITE_VALUE_QUOTING_CHAR)
                     for v in value[1:-1].split(COMPOSITE_VALUE_SEPARATOR)]

        if len(value) != len(self.fields):
            raise ValueError("%s values must have length %d; "
                             "the length of %r is %d." % (self.name,
                             len(self.fields), value, len(value)))
        value = [f.to_python(v) for f, v in zip(self.fields, value)]
        return value

    def get_lookup_constraint(self, constraint_class, alias, targets,
                              sources, lookup_type, raw_value):
        if lookup_type == 'exact':
            value = self.to_python(raw_value)
            root_constraint = constraint_class()
            for target, source, val in zip(targets, sources, value):
                root_constraint.add(
                    (Constraint(alias, target.column, source), lookup_type, val),
                    AND)
        elif lookup_type == 'in':
            values = [self.to_python(val) for val in raw_value]
            root_constraint = get_composite_in_constraint(
                constraint_class, alias, targets, sources, values)
        else:
            raise TypeError("Lookup type %r not supported with composite "
                            "fields." % lookup_type)
        return root_constraint

def get_composite_value_class(name, fields):
    """
    Returns a namedtuple subclass with our custom unicode representation.
    """
    nt = namedtuple(name, fields)

    @python_2_unicode_compatible
    class CompositeValue(nt):
        def __str__(self):
            return '(' + COMPOSITE_VALUE_SEPARATOR.join(
                    quote(force_text(v),
                          unsafe_chars=COMPOSITE_VALUE_SEPARATOR,
                          escape=COMPOSITE_VALUE_QUOTING_CHAR)
                    for v in self) + ')'

        def __eq__(self, other):
            if isinstance(other, tuple):
                return tuple(self) == other
            return False

    return CompositeValue


def get_composite_in_constraint(constraint_class, alias, targets, sources,
                                values):
    root_constraint = constraint_class()
    columns = [t.column for t in targets]
    root_constraint.add(InConstraint(alias, columns, sources, values), AND)

    return root_constraint
