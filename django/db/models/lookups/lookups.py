from datetime import datetime
from itertools import repeat

from django.core import exceptions
from django.db.models.sql.datastructures import EmptyResultSet
from django.db.models.lookups.backwards_compat import BackwardsCompatLookup
from django.db.models.fields import Field
from django.utils import six

# We have two different paths to solve a lookup. BackwardsCompatLookup tries
# to guarantee that Fields with overridden get[_db]_prep_lookup defined will
# still work. The new code has very different implementation. The rest of this
# docs is about the new Lookup code path.
#
# We are using "lhs" and "rhs" terms here. "lhs" means the the "column" we are
# comparing against (though it could as well be a computed value, like
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

    def __init__(self, field, nested_lookups):
        self.field = field
        if nested_lookups:
            raise LookupError('The lookup "%s" does not support nested lookups' %
                              (self.lookup_name))

    def make_atom(self, lvalue, value_annotation, params_or_value, qn,
                  connection, field=None):
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
        lhs_clause, params = self.prepare_lhs(lvalue, qn, connection)
        rhs_sql, rhs_params = self.common_normalize(params_or_value, qn, connection)
        params.extend(rhs_params)
        return self.as_constraint_sql(qn, connection, lhs_clause, value_annotation, rhs_sql, params)

    def prepare_lhs(self, lvalue, qn, connection, lhs_only=False):
        """
        Returns the SQL fragment used for the left-hand side of a column
        constraint (for example, the "T1.foo" portion in the clause
        "WHERE ... T1.foo = 6"). The lvalue can also be something that
        knows how to turn itself into SQL by an as_sql() method.
        """
        if hasattr(lvalue, 'as_sql'):
            return lvalue.as_sql(qn, connection)
        if isinstance(lvalue, six.string_types):
            return lvalue, []
        field = lvalue.field
        table_alias, name = lvalue.alias, lvalue.col
        if table_alias:
            lhs = '%s.%s' % (qn(table_alias), qn(name))
        else:
            lhs = qn(name)
        db_type = field.db_type(connection) if field else None
        return connection.ops.field_cast_sql(db_type) % lhs, []

    def get_prep_lookup(self, field, value):
        """
        Does some backend independent type checks and conversions to the
        value.

        This method is called when the constraint is added to WhereNode. The
        reason we need to do a first-stage prepare is that we will do some
        conversions (for example Model -> pk) and type safety checks.
        """
        if hasattr(value, 'prepare'):
            return value.prepare()
        if hasattr(value, '_prepare'):
            return value._prepare()
        if self.rhs_prepare == self.FIELD_PREPARE:
            value = self.field.lookup_prep(self.lookup_name, value)
        elif self.rhs_prepare == self.LIST_FIELD_PREPARE:
            value = [self.field.lookup_prep(self.lookup_name, v) for v in value]
        return value

    def common_normalize(self, value, qn, connection):
        """
        Normalizes the given value. Usually this means turning the value into
        types acceptable by the backend (through field.get_db_prep_value).

        If the value is something which knows how to produce SQL, then we do
        that instead. A lookup of somefield__in=qs is an example of this case.
        """
        # We have three different ways of "turn into SQL".
        if hasattr(value, 'get_compiler'):
            value = value.get_compiler(connection=connection)
        if hasattr(value, 'as_sql') or hasattr(value, '_as_sql'):
            if hasattr(value, 'as_sql'):
                return value.as_sql(qn, connection)
            else:
                return value._as_sql(connection=connection)
        if self.rhs_prepare == self.RAW:
            params = [value]
        elif self.rhs_prepare == self.FIELD_PREPARE:
            params = [self.field.get_db_prep_value(value, connection, False)]
        elif self.rhs_prepare == self.LIST_FIELD_PREPARE:
            params = [self.field.get_db_prep_value(v, connection, False) for v in value]
        return None, params

    def cast_sql(self, value_annotation, connection):
        """
        In some cases we need a cast for the column, this produces the cast
        SQL or just a %s placeholder if no cast is needed...
        """
        if value_annotation is datetime:
            return connection.ops.datetime_cast_sql()
        else:
            return "%s"

    def rhs_format(self, value_annotation, connection, rhs_sql):
        """
        Create placeholders for the params. Extra can come at least from
        SQLEvaluator (which is a way to turn F() into SQL).
        """
        format = self.cast_sql(value_annotation, connection)
        if rhs_sql:
            rhs_sql = '(%s)' % rhs_sql
            format = format % rhs_sql
        return format

    def as_constraint_sql(self, qn, connection, lhs_clause, value_annotation, rhs_sql,
                          params):
        raise NotImplementedError

    def as_sql(self, qn, connection, col):
        return self.prepare_lhs(col, qn, connection, lhs_only=True)

class SimpleLookup(Lookup):
    def as_constraint_sql(self, qn, connection, lhs_clause, value_annotation, rhs_sql, params):
        rhs_format = self.rhs_format(value_annotation, connection, rhs_sql)
        lhs_clause = connection.ops.lookup_cast(self.lookup_name) % lhs_clause
        rhs_clause = connection.operators[self.lookup_name] % rhs_format
        return '%s %s' % (lhs_clause, rhs_clause), params

class Exact(SimpleLookup):
    lookup_name = 'exact'
    rhs_prepare = Lookup.FIELD_PREPARE
Field.lookups['exact'] = Exact

class IsNull(Lookup):
    lookup_name = 'isnull'
    rhs_prepare = Lookup.RAW

    def __init__(self, field=None, rest_of_lookups=None):
        self.field = field
        if rest_of_lookups:
            raise LookupError('The lookup "%s" does not support nested lookups' %
                              (self.lookup_name))

    def make_atom(self, lvalue, value_annotation, params_or_value, qn,
                  connection, field=None):
        lhs_clause = self.prepare_lhs(lvalue, qn, connection)
        return ('%s IS %sNULL' % (lhs_clause[0], (not value_annotation and 'NOT ' or '')),
                lhs_clause[1])
Field.lookups['isnull'] = IsNull

class LessThan(SimpleLookup):
    lookup_name = 'lt'
    rhs_prepare = Lookup.FIELD_PREPARE
Field.lookups['lt'] = LessThan

class EqOrLessThan(SimpleLookup):
    lookup_name = 'lte'
    rhs_prepare = Lookup.FIELD_PREPARE
Field.lookups['lte'] = EqOrLessThan

class GreaterThan(SimpleLookup):
    lookup_name = 'gt'
    rhs_prepare = Lookup.FIELD_PREPARE
Field.lookups['gt'] = GreaterThan

class EqOrGreaterThan(SimpleLookup):
    lookup_name = 'gte'
    rhs_prepare = Lookup.FIELD_PREPARE
Field.lookups['gte'] = EqOrGreaterThan

class PatternLookup(SimpleLookup):
    rhs_prepare = Lookup.RAW
    pattern = ""

    def common_normalize(self, params, qn, connection):
        rhs_sql, params = super(PatternLookup, self).common_normalize(
            params, qn, connection)
        return rhs_sql, [self.pattern % connection.ops.prep_for_like_query(params[0])]

class Contains(PatternLookup):
    lookup_name = 'contains'
    pattern = "%%%s%%"
Field.lookups['contains'] = Contains

class IContains(Contains):
    lookup_name = 'icontains'
Field.lookups['icontains'] = IContains

class StartsWith(PatternLookup):
    lookup_name = 'startswith'
    pattern = "%s%%"
Field.lookups['startswith'] = StartsWith

class IStartsWith(StartsWith):
    lookup_name = 'istartswith'
Field.lookups['istartswith'] = IStartsWith

class EndsWith(PatternLookup):
    lookup_name = 'endswith'
    pattern = '%%%s'
Field.lookups['endswith'] = EndsWith

class IEndsWith(EndsWith):
    lookup_name = 'iendswith'
Field.lookups['iendswith'] = IEndsWith

class IExact(SimpleLookup):
    lookup_name = 'iexact'
    rhs_prepare = Lookup.RAW

    def common_normalize(self, params, qn, connection):
        rhs_sql, params = super(IExact, self).common_normalize(
            params, qn, connection)
        return rhs_sql, [connection.ops.prep_for_iexact_query(params[0])]
Field.lookups['iexact'] = IExact

# The date lookups (__year, __month, ...) could be refactored to use some
# base classes and then produce efficient SQL for lt, gt, exact and so on
# lookups. Currently only year__exact is done in this way.
class YearExact(Exact):

    def __init__(self, field, rest_of_lookups, source_field):
        self.source_field = source_field
        super(YearExact, self).__init__(field, rest_of_lookups)

    def common_normalize(self, params, qn, connection):
        rhs_sql, params = super(YearExact, self).common_normalize(params, qn, connection)
        if rhs_sql:
            return rhs_sql, params
        intval = int(params[0])
        if self.source_field.get_internal_type() == 'DateField':
            return rhs_sql, connection.ops.year_lookup_bounds_for_date_field(intval)
        else:
            return rhs_sql, connection.ops.year_lookup_bounds(intval)

    def as_constraint_sql(self, qn, connection, lhs_clause, value_annotation, rhs_sql,
                          params):
        if rhs_sql:
            lhs_clause = connection.ops.date_extract_sql('year', lhs_clause)
            return super(YearExact, self).as_constraint_sql(
                qn, connection, lhs_clause, value_annotation, rhs_sql, params)
        return '%s BETWEEN %%s AND %%s' % lhs_clause, params


class Year(SimpleLookup):
    rhs_prepare = Lookup.RAW

    def __init__(self, field, rest_of_lookups):
        # Year deals with "exact" specially - it doesn't use extract year from
        # the col + intereger comparison for performance reasons. It would be a
        # good idea to do the same for other easy comparisons, too (__lt, __gt,
        # ...)
        from django.db.models.fields import IntegerField
        self.field = IntegerField()
        if rest_of_lookups and rest_of_lookups[0] != 'exact':
            self.nested_lookup = self.field.get_lookup(rest_of_lookups, self.field)
        else:
            self.nested_lookup = YearExact(self.field, rest_of_lookups, field)
        self.lookup_name = self.nested_lookup.lookup_name

    def common_normalize(self, params, qn, connection):
        return self.nested_lookup.common_normalize(params, qn, connection)

    def prepare_lhs(self, lvalue, qn, connection, lhs_only=False):
        lhs_clause, params = super(Year, self).prepare_lhs(lvalue, qn, connection)
        if self.nested_lookup.lookup_name != 'exact' or lhs_only:
            # exact wants the raw date, others want the year extracted out of the date.
            lhs_clause = connection.ops.date_extract_sql('year', lhs_clause)
        lhs_clause, inner_params = self.nested_lookup.prepare_lhs(lhs_clause, qn, connection)
        params.extend(inner_params)
        return lhs_clause, params

    def as_constraint_sql(self, qn, connection, lhs_clause, value_annotation, extra, params):
        return self.nested_lookup.as_constraint_sql(
            qn, connection, lhs_clause, value_annotation, extra, params)
Field.lookups['year'] = Year

class DateBase(SimpleLookup):
    rhs_prepare = Lookup.RAW

    def __init__(self, field, rest_of_lookups):
        from django.db.models.fields import IntegerField
        self.field = IntegerField()
        if rest_of_lookups and rest_of_lookups[0] != 'exact':
            self.nested_lookup = self.retval_field.get_lookup(rest_of_lookups, self.field)
        else:
            assert len(rest_of_lookups) <= 1
            self.nested_lookup = Exact(self.field, rest_of_lookups)
        self.datetype = self.lookup_name
        self.lookup_name = self.nested_lookup.lookup_name

    def prepare_lhs(self, lvalue, qn, connection, lhs_only=False):
        lhs_clause, params = super(DateBase, self).prepare_lhs(lvalue, qn, connection)
        return connection.ops.date_extract_sql(self.datetype, lhs_clause), params

    def common_normalize(self, params, qn, connection):
        return self.nested_lookup.common_normalize(params, qn, connection)

    def as_constraint_sql(self, qn, connection, lhs_clause, value_annotation, rhs_sql, params):
        return self.nested_lookup.as_constraint_sql(qn, connection, lhs_clause, value_annotation,
                                                    rhs_sql, params)

class Month(DateBase):
    lookup_name = 'month'
Field.lookups['month'] = Month

class Day(DateBase):
    lookup_name = 'day'
Field.lookups['day'] = Day

class WeekDay(DateBase):
    lookup_name = 'week_day'
Field.lookups['week_day'] = WeekDay

class In(SimpleLookup):
    lookup_name = 'in'
    rhs_prepare = Lookup.LIST_FIELD_PREPARE

    def cast_sql(self, value_annotation, connection):
        if not value_annotation:
            raise EmptyResultSet
        return '%s'

    def as_constraint_sql(self, qn, connection, lhs_clause, value_annotation, rhs_sql, params):
        cast_sql = self.cast_sql(value_annotation, connection)
        if rhs_sql:
            return '%s IN (%s)' % (lhs_clause, rhs_sql), params
        # Move rest of me into connection...
        max_in_list_size = connection.ops.max_in_list_size()
        if max_in_list_size and len(params) > max_in_list_size:
            # Break up the params list into an OR of manageable chunks.
            in_clause_elements = ['(']
            for offset in xrange(0, len(params), max_in_list_size):
                if offset > 0:
                    in_clause_elements.append(' OR ')
                in_clause_elements.append('%s IN (' % lhs_clause)
                group_size = min(len(params) - offset, max_in_list_size)
                param_group = ', '.join(repeat(cast_sql, group_size))
                in_clause_elements.append(param_group)
                in_clause_elements.append(')')
            in_clause_elements.append(')')
            return ''.join(in_clause_elements), params
        else:
            return ('%s IN (%s)' %
                    (lhs_clause, ', '.join(repeat(cast_sql, len(params)))),
                    params)
Field.lookups['in'] = In

class Range(Lookup):
    lookup_name = 'range'
    rhs_prepare = Lookup.LIST_FIELD_PREPARE

    def as_constraint_sql(self, qn, connection, lhs_clause, value_annotation, extra, params):
        return '%s BETWEEN %%s AND %%s' % lhs_clause, params
Field.lookups['range'] = Range

class Search(Lookup):
    lookup_name = 'search'
    rhs_prepare = Lookup.RAW

    def as_constraint_sql(self, qn, connection, lhs_clause, value_annotation, extra, params):
        return connection.ops.fulltext_search_sql(lhs_clause), params
Field.lookups['search'] = Search

class Regex(Lookup):
    lookup_name = 'regex'

    def as_constraint_sql(self, qn, connection, lhs_clause, value_annotation, extra, params):
        """
        Regex lookups are implemented partly by connection.operators... Except
        when not.
        """
        if self.lookup_name in connection.operators:
            lhs_clause = connection.ops.lookup_cast(self.lookup_name) % lhs_clause
            rhs_format = self.rhs_format(value_annotation, connection, extra)
            rhs_clause = connection.operators[self.lookup_name] % rhs_format
            return '%s %s' % (lhs_clause, rhs_clause), params
        else:
            cast_sql = self.cast_sql(value_annotation, connection)
            return connection.ops.regex_lookup(self.lookup_name) % (lhs_clause, cast_sql), params
Field.lookups['regex'] = Regex

class IRegex(Regex):
    lookup_name = 'iregex'
Field.lookups['iregex'] = IRegex

class RelatedLookup(Lookup):
    """
    Related lookup is needed so that we can prepare the values. After that
    we just pass the action to the target field's lookup.

    It would be possible (and likely wise) to get rid of RelatedLookup -
    we could do the value transformation directly in get_lookup().
    """
    def __init__(self, lookup, source_field, target_field):
        self.lookup = lookup
        self.lookup_name = lookup.lookup_name
        self.source_field = source_field
        self.target_field = target_field

    def get_prep_lookup(self, field, value):
        """
        Note: We must convert any "model" value on add from model to something
        else. __deepcopy__ goes seriously wrong if we don't do this.

        This is somewhat non-dry compared to the default get_pre_lookup...
        """
        if isinstance(self.lookup, BackwardsCompatLookup):
            # Let it do whatever it needs to do...
            return self.lookup.get_prep_lookup(field, value)
        if hasattr(value, 'prepare'):
            return value.prepare()
        if hasattr(value, '_prepare'):
            return value._prepare()
        if self.lookup.rhs_prepare == self.LIST_FIELD_PREPARE:
            value = [self.convert_value(v) for v in value]
        else:
            value = self.convert_value(value)
        return value

    def make_atom(self, lvalue, value_annotation, params_or_value, qn,
                  connection, field=None):
        if isinstance(self.lookup, BackwardsCompatLookup):
            # Let it do whatever it needs to do...
            return self.lookup.make_atom(lvalue, value_annotation, params_or_value,
                                         qn, connection)
        return self.lookup.make_atom(lvalue, value_annotation, params_or_value, qn,
                                     connection, field=self.target_field)

    def convert_value(self, value):
        # Value may be a primary key, or an object held in a relation.
        # If it is an object, then we need to get the primary key value for
        # that object. In certain conditions (especially one-to-one relations),
        # the primary key may itself be an object - so we need to keep drilling
        # down until we hit a value that can be used for a comparison.

        # In the case of an FK to 'self', this check allows to_field to be used
        # for both forwards and reverse lookups across the FK. (For normal FKs,
        # it's only relevant for forward lookups).
        if isinstance(value, self.source_field.rel.to):
            field_name = getattr(self.source_field.rel, 'field_name')
        else:
            field_name = None
        try:
            while True:
                if field_name is None:
                    field_name = value._meta.pk.name
                value = getattr(value, field_name)
                field_name = None
        except AttributeError:
            pass
        except exceptions.ObjectDoesNotExist:
            value = None
        return value
