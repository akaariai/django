"""
Useful auxilliary data structures for query construction. Not useful outside
the SQL domain.
"""
# TODO: move Col here.
from datetime import datetime

from django.conf import settings
from django.db.models.lookups import Col
from django.db.backends.util import typecast_timestamp, typecast_date
from django.utils import timezone


class EmptyResultSet(Exception):
    pass


class MultiJoin(Exception):
    """
    Used by join construction code to indicate the point at which a
    multi-valued join was attempted (if the caller wants to treat that
    exceptionally).
    """
    def __init__(self, names_pos, path_with_names):
        self.level = names_pos
        # The path travelled, this includes the path to the multijoin.
        self.names_with_path = path_with_names


class Empty(object):
    pass


class Date(Col):
    """
    Add a date selection column.
    """
    def __init__(self, alias, field, lookup_type):
        super(Date, self).__init__(alias, field)
        self.lookup_type = lookup_type

    def relabeled_clone(self, change_map):
        return self.__class__(change_map.get(self.alias, self.alias), self.field,
                              self.lookup_type)

    def as_sql(self, qn, connection):
        sql, params = super(Date, self).as_sql(qn, connection)
        return connection.ops.date_trunc_sql(self.lookup_type, sql), params

    def convert_value(self, value, connection):
        if connection.features.needs_datetime_string_cast:
            value = typecast_date(str(value))
        if isinstance(value, datetime):
            value = value.date()
        return value

class DateTime(Col):
    """
    Add a datetime selection column.
    """
    def __init__(self, alias, field, lookup_type, tzinfo, tzname):
        super(DateTime, self).__init__(alias, field)
        self.lookup_type = lookup_type
        self.tzname = tzname
        self.tzinfo = tzinfo

    def relabeled_clone(self, change_map):
        return self.__class__(
            change_map.get(self.alias, self.alias), self.field,
            self.lookup_type, self.tzinfo, self.tzname
        )

    def as_sql(self, qn, connection):
        col, params = super(DateTime, self).as_sql(qn, connection)
        assert not params, "Params not supported"
        return connection.ops.datetime_trunc_sql(self.lookup_type, col, self.tzname)

    def convert_value(self, value, connection):
        if connection.features.needs_datetime_string_cast:
            value = typecast_timestamp(str(value))
        if settings.USE_TZ:
            if value is None:
                raise ValueError("Database returned an invalid value "
                                 "in QuerySet.dates(). Are time zone "
                                 "definitions and pytz installed?")
            value = value.replace(tzinfo=None)
            value = timezone.make_aware(value, self.tzinfo)
        return value
