from django.conf import settings
from django.utils import timezone

class UnsupportedLookup(Exception):
    pass

class Col(object):
    def __init__(self, alias, column):
        self.alias, self.column = alias, column

    def as_sql(self, qn, connection):
        return "%s.%s" % (qn(self.alias), qn(self.column)), []

    def relabeled_clone(self, change_map):
        return self.__class__(change_map.get(self.alias, self.alias),
                              self.column)

    def get_cols(self):
        return [(self.alias, self.column)]

default_lookups = {}

class Lookup(object):
    """
    A lookup can be used in two contexts. As an boolean condition, for example
    generating ("somecol < %s", [someval]), or as a value generating
    expression ("EXTRACT YEAR FROM somecol).

    If the lookup supports the boolean condition operation, then it must
    implement:
        as_sql(qn, connection)
    method. If it supports value generation, then it must implement:
        as_expression_sql(qn, connection)

    Note that the base Lookup class doesn't implement either of the conditions.

    A lookup should implement relabeled_clone() method. This is called when
    the alias used by the Lookup changes. Otherwise a Lookup should be
    immutable.
    """

class SimpleLookup(Lookup):
    def __init__(self, lhs, value, field):
        self.lhs, self.value, self.field = lhs, value, field
        self.value = self.get_prep_lookup()

    def get_prep_lookup(self):
        return self.field.get_prep_lookup(self.lookup_type, self.value)

    def process_lhs(self, qn, connection):
        lhs_sql, params = self.lhs.as_sql(qn, connection)
        return connection.ops.lookup_cast(self.lookup_type) % lhs_sql, params

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

    def get_db_prep_lookup(self, value, connection):
        return (
            '%s', self.field.get_db_prep_lookup(
            self.lookup_type, value, connection, prepared=True))

    def get_rhs_op(self, qn, connection, rhs):
        return connection.operators[self.lookup_type] % rhs

    def as_sql(self, qn, connection):
        rhs, value = self.process_rhs(qn, connection)
        lhs, params = self.process_lhs(qn, connection)
        params.extend(value)
        final_rhs = self.get_rhs_op(qn, connection, rhs)
        return "%s %s" % (lhs, final_rhs), params

    def relabeled_clone(self, change_map):
        if hasattr(self.value, 'relabeled_clone'):
            value = self.value.relabeled_clone(change_map)
        else:
            value = self.value
        return self.__class__(self.lhs.relabeled_clone(change_map),
                              value, self.field)

    def get_cols(self):
        return self.lhs.get_cols()


class Exact(SimpleLookup):
    lookup_type = 'exact'
default_lookups['exact'] = Exact

class IExact(SimpleLookup):
    lookup_type = 'iexact'
default_lookups['iexact'] = IExact

class Contains(SimpleLookup):
    lookup_type = 'contains'
default_lookups['contains'] = Contains

class Contains(SimpleLookup):
    lookup_type = 'contains'
default_lookups['contains'] = Contains

class IContains(SimpleLookup):
    lookup_type = 'icontains'
default_lookups['icontains'] = IContains

class GreaterThan(SimpleLookup):
    lookup_type = 'gt'
default_lookups['gt'] = GreaterThan

class GreaterThanOrEqual(SimpleLookup):
    lookup_type = 'gte'
default_lookups['gte'] = GreaterThanOrEqual

class LessThan(SimpleLookup):
    lookup_type = 'lt'
default_lookups['lt'] = LessThan

class LessThanOrEqual(SimpleLookup):
    lookup_type = 'lte'
default_lookups['lte'] = LessThanOrEqual

class In(SimpleLookup):
    lookup_type = 'in'

    def get_db_prep_lookup(self, value, connection):
        params = self.field.get_db_prep_lookup(
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

class StartsWith(SimpleLookup):
    lookup_type = 'startswith'
default_lookups['startswith'] = StartsWith

class IStartsWith(SimpleLookup):
    lookup_type = 'istartswith'
default_lookups['istartswith'] = IStartsWith

class EndsWith(SimpleLookup):
    lookup_type = 'endswith'
default_lookups['endswith'] = EndsWith

class IEndsWith(SimpleLookup):
    lookup_type = 'iendswith'
default_lookups['iendswith'] = IEndsWith


class Extract(object):
    def __init__(self, lhs, field):
        self.lhs, self.field = lhs, field

    def process_lhs(self, qn, connection):
        lhs_sql, params = self.lhs.as_sql(qn, connection)

    def as_sql(self, qn, connection):
        return self.process_lhs(qn, connection)

    def relabeled_clone(self, change_map):
        return self.__class__(self.lhs.relabeled_clone(change_map),
                              self.field)

    def get_cols(self):
        return self.lhs.get_cols()

class Between(SimpleLookup):
    def get_rhs_op(self, qn, connection, rhs):
        return "BETWEEN %s AND %s" % (rhs, rhs)

class Year(Between):
    lookup_type = 'year'
default_lookups['year'] = Year

class Range(Between):
    lookup_type = 'range'
default_lookups['range'] = Range

class DateExtract(Extract):
    def __init__(self, lhs, extract_type):
        self.lhs, self.extract_type = lhs, extract_type

    def process_lhs(self, qn, connection):
        lhs, params = self.lhs.as_sql(qn, connection)
        tzname = timezone.get_current_timezone_name() if settings.USE_TZ else None
        sql, tz_params = connection.ops.datetime_extract_sql(self.extract_type, lhs, tzname)
        return ('%s' % sql, tz_params + params)

    def relabeled_clone(self, change_map):
        return self.__class__(self.lhs.relabeled_clone(change_map), self.extract_type)

class DateLookup(SimpleLookup):

    def process_lhs(self, qn, connection):
        extract = DateExtract(self.lhs, self.lookup_type)
        lhs_sql, params = extract.as_sql(qn, connection)
        return connection.ops.lookup_cast(self.lookup_type) % lhs_sql, params

    def get_rhs_op(self, qn, connection, rhs):
        return '= %s' % rhs

class Month(DateLookup):
    lookup_type = 'month'
default_lookups['month'] = Month

class Day(DateLookup):
    lookup_type = 'day'
default_lookups['day'] = Day

class WeekDay(DateLookup):
    lookup_type = 'week_day'
default_lookups['week_day'] = WeekDay

class Hour(DateLookup):
    lookup_type = 'hour'
default_lookups['hour'] = Hour

class Minute(DateLookup):
    lookup_type = 'minute'
default_lookups['minute'] = Minute

class Second(DateLookup):
    lookup_type = 'second'
default_lookups['second'] = Second

class IsNull(SimpleLookup):
    lookup_type = 'isnull'

    def as_sql(self, qn, connection):
        sql, params = self.lhs.as_sql(qn, connection)
        if self.value:
            return "%s IS NULL" % sql, params
        else:
            return "%s IS NOT NULL" % sql, params
default_lookups['isnull'] = IsNull

class Search(SimpleLookup):
    lookup_type = 'search'
default_lookups['search'] = Search

class Regex(SimpleLookup):
    lookup_type = 'regex'
default_lookups['regex'] = Regex

class IRegex(SimpleLookup):
    lookup_type = 'iregex'
default_lookups['iregex'] = IRegex
