from django.conf import settings
from django.utils import timezone
from django.utils.functional import cached_property

class UnsupportedLookup(Exception):
    pass

default_lookups = {}
NoValueMarker = object()

class Lookup(object):
    """
    A lookup needs to respond to three methods:
        as_sql(qn, connection): returns query string for this lookup.
        relabeled_clone(change_map): returns a new instance of this lookup
                                     with aliases changed.
        get_cols(): what columns are used by this lookup. Needed to build
                    GROUP BY clause for aggregation.

    If the lookup can be used in chained context, then it needs to also
    implement get_lookup(lookup).

    The lookup will be constructed by classmethod build_lookup(...).
    """
    is_aggregate = False
    convert_value = None

    def as_sql(self, qn, connection):
        raise NotImplementedError

    def relabeled_clone(self, change_map):
        raise NotImplementedError

    def get_lookup(self, lookup):
        raise NotImplementedError

    def get_cols(self):
        raise NotImplementedError

    @classmethod
    def build_lookup(cls, lookup_rewriter, target_cols, source_field,
                     constraint_class, value=NoValueMarker):
        raise NotImplementedError


class SimpleLookup(Lookup):
    """
    A simple lookup
    """
    supports_nesting = False
    supports_filtering = True
    lookup_type = None

    @classmethod
    def build_lookup(cls, lookup_rewriter, target_cols, source_field,
                     constraint_class, value=NoValueMarker):
        """
        The params are as follows:
            lookup_rewriter is something the query class can offer to rewrite lookup
            (for example, norel databases could use this to offer alternate
            implementation).

            field is the originating field. For concrete fields this will be the same
            as sources[0].

            sources is the list of fields the lookup works against.

            targets contain "trimmed" fields for sources.

            For example, if you have user_id -> user.pk relation, then in a user__pk
            lookup, the sources is [user.pk], the targets is [user_id]. That is, the
            targets will always have the same value as the sources.

            The constraint_class is something alike WhereNode, it can be used to
            build boolean trees if needed by the lookup.

            The value, if given, is the raw value supplied by the user. If the
            value is NoValueMarker, it means this lookup is used in nested
            context (that is, this lookup should only build the LHS value).
        """
        # Simple lookup targets only a single field, so assert that targets and
        # sources contain only a single field.
        assert len(target_cols) == 1, 'Only single field allowed'
        # lookup_rewriter can be used to provide alternate implementations
        # (for example if some "NoSQL" database needs that).
        lhs = target_cols[0]
        lookup_implementation = lookup_rewriter(lhs.field, cls.lookup_type) or cls
        return lookup_implementation(
            constraint_class, lhs, source_field or lhs.field, value)

    def __init__(self, constraint_class, lhs, field, value=NoValueMarker):
        self.constraint_class, self.lhs, self.value = constraint_class, lhs, value
        self.field = field
        if self.value is not NoValueMarker:
            if not self.supports_filtering:
                raise LookupError("This lookup can't be used as filter condition!")
            self.value = self.get_prep_lookup()
        elif not self.supports_nesting:
            raise LookupError("This lookup can't be used in nested context!")

    def get_db_prep_lookup(self, value, connection):
        return (
            '%s', self.field.get_db_prep_lookup(
            self.lookup_type, value, connection, prepared=True))

    def get_prep_lookup(self):
        return self.field.get_prep_lookup(self.lookup_type, self.value)

    def process_lhs(self, qn, connection):
        lhs_sql, params = self.lhs.as_sql(qn, connection)
        return lhs_sql, params

    def process_rhs(self, qn, connection):
        value = self.value
        if hasattr(self.value, 'get_compiler'):
            value = value.get_compiler(connection=connection)
        if hasattr(value, 'as_sql'):
            sql, params = value.as_sql(qn, connection)
            return '(' + sql + ')', params
        if hasattr(value, '_as_sql'):
            sql, params = value._as_sql(connection=connection)
            return '(' + sql + ')', params
        else:
            return self.get_db_prep_lookup(value, connection)

    def get_lhs_rhs(self, qn, connection):
        rhs, value = self.process_rhs(qn, connection)
        lhs, params = self.process_lhs(qn, connection)
        params.extend(value)
        return rhs, lhs, params

    def as_nested_sql(self, qn, connection):
        return self.process_lhs(qn, connection)

    def get_rhs_op(self, qn, connection, rhs):
        return rhs

    def as_sql(self, qn, connection):
        if self.value is NoValueMarker:
            return self.as_nested_sql(qn, connection)
        rhs, lhs, params = self.get_lhs_rhs(qn, connection)
        final_rhs = self.get_rhs_op(qn, connection, rhs)
        return "%s %s" % (lhs, final_rhs), params

    def relabeled_clone(self, change_map):
        if hasattr(self.value, 'relabeled_clone'):
            value = self.value.relabeled_clone(change_map)
        else:
            value = self.value
        return self.__class__(
            self.constraint_class, self.lhs.relabeled_clone(change_map),
            self.field, value)

    def get_cols(self):
        cols = self.lhs.get_cols()
        if hasattr(self.value, 'get_cols'):
            cols.extend(self.value.get_cols())
        return cols

    def get_lookup(self, lookup):
        if self.supports_nesting:
            return self.output_type.get_lookup(lookup)
        return None

    @cached_property
    def output_type(self):
        # The default is that the transformation doesn't change the type of
        # LHS. This can be overridden, for example if you extract year from
        # datetime.
        return self.lhs.output_type

    def remove_from_query(self, query):
        self.lhs.remove_from_query(query)
        if hasattr(self.value, 'remove_from_query'):
            self.value.remove_from_query(query)

class DjangoLookup(SimpleLookup):

    def get_rhs_op(self, qn, connection, rhs):
        return connection.operators[self.lookup_type] % rhs

    def process_lhs(self, qn, connection):
        lhs_sql, params = super(DjangoLookup, self).process_lhs(qn, connection)
        field_internal_type = self.lhs.output_type.get_internal_type()
        db_type = self.lhs.output_type
        lhs_sql = connection.ops.field_cast_sql(db_type, field_internal_type) % lhs_sql
        return connection.ops.lookup_cast(self.lookup_type) % lhs_sql, params


class Exact(DjangoLookup):
    lookup_type = 'exact'
default_lookups['exact'] = Exact

class IExact(DjangoLookup):
    lookup_type = 'iexact'
default_lookups['iexact'] = IExact

class Contains(DjangoLookup):
    lookup_type = 'contains'
default_lookups['contains'] = Contains

class Contains(DjangoLookup):
    lookup_type = 'contains'
default_lookups['contains'] = Contains

class IContains(DjangoLookup):
    lookup_type = 'icontains'
default_lookups['icontains'] = IContains

class GreaterThan(DjangoLookup):
    lookup_type = 'gt'
default_lookups['gt'] = GreaterThan

class GreaterThanOrEqual(DjangoLookup):
    lookup_type = 'gte'
default_lookups['gte'] = GreaterThanOrEqual

class LessThan(DjangoLookup):
    lookup_type = 'lt'
default_lookups['lt'] = LessThan

class LessThanOrEqual(DjangoLookup):
    lookup_type = 'lte'
default_lookups['lte'] = LessThanOrEqual

class In(DjangoLookup):
    lookup_type = 'in'

    def get_db_prep_lookup(self, value, connection):
        params = self.lhs.field.get_db_prep_lookup(
            self.lookup_type, value, connection, prepared=True)
        if not params:
            # TODO: check why this leads to circular import
            from django.db.models.sql.datastructures import EmptyResultSet
            raise EmptyResultSet
        placeholder = '(' + ', '.join('%s' for p in params) + ')'
        return (placeholder, params)

    def get_rhs_op(self, qn, connection, rhs):
        return 'IN %s' % rhs
default_lookups['in'] = In

class StartsWith(DjangoLookup):
    lookup_type = 'startswith'
default_lookups['startswith'] = StartsWith

class IStartsWith(DjangoLookup):
    lookup_type = 'istartswith'
default_lookups['istartswith'] = IStartsWith

class EndsWith(DjangoLookup):
    lookup_type = 'endswith'
default_lookups['endswith'] = EndsWith

class IEndsWith(DjangoLookup):
    lookup_type = 'iendswith'
default_lookups['iendswith'] = IEndsWith


class Between(DjangoLookup):
    def get_rhs_op(self, qn, connection, rhs):
        return "BETWEEN %s AND %s" % (rhs, rhs)

class Year(Between):
    lookup_type = 'year'
default_lookups['year'] = Year

class Range(Between):
    lookup_type = 'range'
default_lookups['range'] = Range


class DateLookup(DjangoLookup):

    def process_lhs(self, qn, connection):
        lhs, params = super(DateLookup, self).process_lhs(qn, connection)
        tzname = timezone.get_current_timezone_name() if settings.USE_TZ else None
        sql, tz_params = connection.ops.datetime_extract_sql(self.extract_type, lhs, tzname)
        return connection.ops.lookup_cast(self.lookup_type) % sql, tz_params

    def get_rhs_op(self, qn, connection, rhs):
        return '= %s' % rhs

class Month(DateLookup):
    lookup_type = 'month'
    extract_type = 'month'
default_lookups['month'] = Month

class Day(DateLookup):
    lookup_type = 'day'
    extract_type = 'day'
default_lookups['day'] = Day

class WeekDay(DateLookup):
    lookup_type = 'week_day'
    extract_type = 'week_day'
default_lookups['week_day'] = WeekDay

class Hour(DateLookup):
    lookup_type = 'hour'
    extract_type = 'hour'
default_lookups['hour'] = Hour

class Minute(DateLookup):
    lookup_type = 'minute'
    extract_type = 'minute'
default_lookups['minute'] = Minute

class Second(DateLookup):
    lookup_type = 'second'
    extract_type = 'second'
default_lookups['second'] = Second

class IsNull(DjangoLookup):
    lookup_type = 'isnull'

    def as_sql(self, qn, connection):
        sql, params = self.lhs.as_sql(qn, connection)
        if self.value:
            return "%s IS NULL" % sql, params
        else:
            return "%s IS NOT NULL" % sql, params
default_lookups['isnull'] = IsNull

class Search(DjangoLookup):
    lookup_type = 'search'
default_lookups['search'] = Search

class Regex(DjangoLookup):
    lookup_type = 'regex'
default_lookups['regex'] = Regex

class IRegex(DjangoLookup):
    lookup_type = 'iregex'
default_lookups['iregex'] = IRegex
