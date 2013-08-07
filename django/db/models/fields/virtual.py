from __future__ import unicode_literals

from collections import namedtuple

from django.db.models import signals
from django.db.models.fields import Field
from django.db.models.sql.where import InConstraint, AND
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
        return None

    def contribute_to_class(self, cls, name):
        super(VirtualField, self).contribute_to_class(cls, name)
        # Virtual fields are descriptors; they are not handled
        # individually at instance level.
        setattr(cls, name, self)

    def get_column(self):
        return None

    def get_enclosed_fields(self):
        return []

    def resolve_basic_fields(self):
        return [f
                for myfield in self.get_enclosed_fields()
                for f in myfield.resolve_basic_fields()]

    def formfield(self):
        return None

    def __get__(self, instance, owner):
        return None

    def __set__(self, instance, value):
        pass


class CompositeField(VirtualField):
    """
    Virtual field type enclosing several atomic fields into one.
    """
    def __init__(self, *fields, **kwargs):
        self.fields = fields
        super(CompositeField, self).__init__(**kwargs)

    def contribute_to_class(self, cls, name):
        super(CompositeField, self).contribute_to_class(cls, name)

        # We can process the fields only after they've been added to the
        # model class.
        def process_enclosed_fields(sender, **kwargs):
            nt_name = "%s_%s" % (cls.__name__, name)
            nt_fields = " ".join(f.name for f in self.fields)
            self.nt = get_composite_value_class(nt_name, nt_fields)

        signals.class_prepared.connect(process_enclosed_fields,
                                       sender=cls, weak=False)

    def get_enclosed_fields(self):
        return self.fields

    def __get__(self, instance, owner):
        if instance is None:
            raise AttributeError("%s can only be retrieved via instance."
                                 % self.name)
        return self.nt._make(getattr(instance, f.attname, None) for f in self.fields)

    def __set__(self, instance, value):
        # Ignore attempts to set to None; deletion code does that and we
        # don't want to throw an exception.
        if value is None:
            return
        value = self.to_python(value)
        for f, val in zip([f.attname for f in self.fields], value):
            setattr(instance, f, val)

    def to_python(self, value):
        if isinstance(value, six.string_types):
            value = [unquote(v, escape=COMPOSITE_VALUE_QUOTING_CHAR)
                     for v in value.split(COMPOSITE_VALUE_SEPARATOR)]

        value = [f.to_python(v) for f, v in zip(self.fields, value)]
        return value


def get_composite_value_class(name, fields):
    """
    Returns a namedtuple subclass with our custom unicode representation.
    """
    nt = namedtuple(name, fields)

    @python_2_unicode_compatible
    class CompositeValue(nt):
        def __str__(self):
            return COMPOSITE_VALUE_SEPARATOR.join(
                    quote(force_text(v),
                          unsafe_chars=COMPOSITE_VALUE_SEPARATOR,
                          escape=COMPOSITE_VALUE_QUOTING_CHAR)
                    for v in self)

    return CompositeValue


def get_composite_in_constraint(constraint_class, alias, targets, sources,
                                values):
    root_constraint = constraint_class()
    columns = [t.column for t in targets]
    root_constraint.add(InConstraint(alias, columns, sources, values), AND)

    return root_constraint
