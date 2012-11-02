from datetime import datetime

from django.db.models.lookups.backwards_compat import BackwardsCompatLookup
from django.db.models.query_utils import QueryWrapper

# We have two different paths to solve a lookup. BackwardsCompatLookup tries
# to guarantee that Fields with overridden get[_db]_prep_lookup defined will
# still work. The new code has very different implementation. The rest of this
# docs is about the new Lookup code path.
#
# We are using "lhs" and "rhs" terms here. "lhs" means the the "column" we are
# comparing against (though it could as well be a computer value, like
# aggregate), "rhs" means the given value, a string or integer for example.
#
# When processing a Lookup to SQL, three things need to happen:
#  1. We need to turn the LHS into SQL. The LHS is either an Aggregate or a
#     Constraint object.
#  2. We need to turn the RHS into properly typed parameters. The RHS can be
#     a raw value, a query a list of values or depending on the field type
#     something else. This value needs to be normalized in to a type the db
#     adapter is expecting.
#  3. Finally, we need to turn these pieces into SQL constraint. Here we could
#     need to turn the SQL into a direct comparison:
#         ('T1."somecol" = %s', [someparam])
#     or maybe to a procedure call:
#         is_subunit('T1."org_id"', %s), [parent_id])
#     No. 3 is implemented by as_sql()
#
# The default implementation passes the RHS normalization to the underlying
# field. This is so that fields don't need all the different lookups just to
# implement different normalization rules.
#
# When turning the Lookup into SQL the API is simple from the caller
# perspective: We have make_atom, which will return SQL + params. The
# implementation of make_atom is totally different for BackwardsCompatLookup
# and new Lookup objects.
#
# For implementing custom lookups the idea is that one needs to just implement
# as_sql() and register the lookup.
#
# Note that a lookup is against single field only - there is currently no
# support for fetching multiple fields for single lookup. This is something
# virtual fields will likely achieve. Of course, if all the fields are in a
# single table a clever hacker will find a way to do multifield comparisons...

class Lookup(object):
    # A name used mostly for internal purposes. This can also be used by custom
    # fields to detect the lookup type.
    lookup_name = None
    # What type of rhs value do we expect? Choices are RAW (do not do anything
    # to the value), LIST (loop through the value and prepare each one
    # separately) and PREPARE (the value must be prepared using the field).
    RAW = object()
    LIST_FIELD_PREPARE = object()
    FIELD_PREPARE = object()
    rhs_prepare = RAW

    def __deepcopy__(self, memo):
        """
        I am immutable!
        """
        return self

    def get_prep_lookup(self, field, value):
        """
        Backwards compatibility (at least for now).
        """
        return value

    def make_atom(self, lvalue, value_annotation, params_or_value, qn,
                  connection):
        """
        Returns (sql, params) for this Lookup.

        The 'lvalue' is either a Constraint of Aggregate. In any case, target
        field must be available from lvalue.field.

        The 'params_or_value' is something we are comparing against - for
        example a raw value, list of values, a queryset, ...

        The 'value_annotation' is a known unknown...

        The 'qn' and connection are quote_name_unless_alias and the used
        connection respectively.
        """
        lhs_clause, db_type = self.prepare_lhs(lvalue, qn, connection)
        params = self.common_normalize(params_or_value, lvalue.field, qn,
                                       connection)
        params = self.normalize_value(params, lvalue.field, qn, connection)
        cast_sql = self.cast_sql(value_annotation, connection)
        if hasattr(params, 'as_sql'):
            extra, params = params.as_sql(qn, connection)
        else:
            extra = ''
        rhs_format = self.rhs_format(cast_sql, extra)
        return self.as_sql(lhs_clause, rhs_format, params, lvalue.field, qn, connection)

    def prepare_lhs(self, lvalue, qn, connection):
        """
        Returns the SQL fragment used for the left-hand side of a column
        constraint (for example, the "T1.foo" portion in the clause
        "WHERE ... T1.foo = 6"). The lvalue can also be something that
        knows how to turn itself into SQL by an as_sql() method.
        """
        field = lvalue.field
        db_type = field.db_type if field else None
        if hasattr(lvalue, 'as_sql'):
            return lvalue.as_sql(qn, connection), db_type
        table_alias, name = lvalue.alias, lvalue.col
        if table_alias:
            lhs = '%s.%s' % (qn(table_alias), qn(name))
        else:
            lhs = qn(name)
        return connection.ops.field_cast_sql(db_type) % lhs, db_type

    def common_normalize(self, value, field, qn, connection):
        if hasattr(value, 'prepare'):
            value = value.prepare()
        if hasattr(value, '_prepare'):
            # Do we really need _two_ prepares...
            value = value._prepare()
        if hasattr(value, 'get_compiler'):
            value = value.get_compiler(connection=connection)
        if hasattr(value, 'as_sql') or hasattr(value, '_as_sql'):
            # If the value has a relabel_aliases method, it will need to
            # be invoked before the final SQL is evaluated
            if hasattr(value, 'relabel_aliases'):
                return value
            if hasattr(value, 'as_sql'):
                sql, params = value.as_sql()
            else:
                sql, params = value._as_sql(connection=connection)
            return QueryWrapper(('(%s)' % sql), params)
        if self.rhs_prepare == self.RAW:
            value = [value]
        elif self.rhs_prepare == self.FIELD_PREPARE:
            value = field.get_prep_value(value)
            value = [field.get_db_prep_value(value, connection, False)]
        elif self.rhs_prepare == self.LIST_FIELD_PREPARE:
            value = [field.get_prep_value(v) for v in value]
            value = [field.get_db_prep_value(v, connection, False) for v in value]
        return value

    def cast_sql(self, value_annotation, connection):
        if value_annotation is datetime:
            return connection.ops.datetime_cast_sql()
        return '%s'

    def rhs_format(self, cast_sql, extra):
        format = cast_sql
        if extra:
            format = cast_sql % extra
        return format
    
    def normalize_value(self, value, field, qn, connection):
        """
        A subclass hook for easier value normalization per lookup.
        """
        return value

    def as_sql(self, lhs_clause, rhs_format, params, field, qn, connection):
        raise NotImplementedError

class RelatedLookup(Lookup):
    def __init__(self, lookup, source_field, target_field):
        self.lookup = lookup
        self.lookup_name = lookup.lookup_name
        self.source_field = source_field
        self.target_field = target_field

    def get_prep_lookup(self, field, value):
        """
        Note: We must convert any "model" value on add from model to something
        else. __deepcopy__ goes seriously wrong if we don't do this...
        """
        if isinstance(self.lookup, BackwardsCompatLookup):
            # Let it do whatever it needs to do...
            return self.lookup.get_prep_lookup(field, value)
        if self.lookup.rhs_prepare == self.LIST_FIELD_PREPARE:
            value = [self.convert_value(self.souce_field, v) for v in value]
        else:
            value = self.convert_value(self.source_field, value)
        return value

    def make_atom(self, lvalue, value_annotation, params_or_value, qn,
                  connection):
        if isinstance(self.lookup, BackwardsCompatLookup):
            # Let it do whatever it needs to do...
            return self.lookup.make_atom(lvalue, value_annotation, params_or_value,
                                         qn, connection)
        return self.lookup.make_atom(lvalue, value_annotation, params_or_value, qn,
                                connection)

    def get_target_field(self, field): 
        while field.rel:
            if hasattr(field.rel, 'field_name'):
                field = field.rel.to._meta.get_field(field.rel.field_name)
            else:
                field = field.rel.to._meta.pk
        return field

    def convert_value(self, field, value):
        # Value may be a primary key, or an object held in a relation.
        # If it is an object, then we need to get the primary key value for
        # that object. In certain conditions (especially one-to-one relations),
        # the primary key may itself be an object - so we need to keep drilling
        # down until we hit a value that can be used for a comparison.

        # In the case of an FK to 'self', this check allows to_field to be used
        # for both forwards and reverse lookups across the FK. (For normal FKs,
        # it's only relevant for forward lookups).
        if isinstance(value, field.rel.to):
            value = getattr(value, self.target_field.attname)
        elif hasattr(value, '_meta'):
            # One can pass in any model. Is this dangerous?
            pk_field = getattr(value, '_meta').pk.attname
            value = getattr(value, pk_field)
        return value

class Exact(Lookup):
    lookup_name = 'exact'
    rhs_prepare = Lookup.FIELD_PREPARE

    def as_sql(self, lhs_clause, rhs_format, params, field, qn, connection):
        rhs_clause = connection.operators['exact'] % rhs_format
        return '%s %s' % (lhs_clause, rhs_clause), params
