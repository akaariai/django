"""
Useful auxilliary data structures for query construction. Not useful outside
the SQL domain.
"""

from datetime import datetime

from django.conf import settings
from django.db.backends.util import typecast_timestamp, typecast_date
from django.db.models.datastructures import RefCol
from django.db.models.fields import DateField, DateTimeField
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


class Date(RefCol):
    """
    Add a date selection column.
    """
    allow_nulls = False

    def __init__(self, lookup, kind):
        super(Date, self).__init__(lookup)
        self.kind = kind

    def as_sql(self, qn, connection):
        sql, params = self.col.as_sql(qn, connection)
        return connection.ops.date_trunc_sql(self.kind, sql), params

    def convert_value(self, value, field, connection):
        if connection.features.needs_datetime_string_cast:
            value = typecast_date(str(value))
        if isinstance(value, datetime):
            value = value.date()
        return value

    def add_to_query(self, *args, **kwargs):
        ret = super(Date, self).add_to_query(*args, **kwargs)
        self._check_field()
        return ret

    def _check_field(self):
        assert isinstance(self.col.field, DateField), \
            "%r isn't a DateField." % self.col.field.name
        if settings.USE_TZ:
            assert not isinstance(self.col.field, DateTimeField), \
                "%r is a DateTimeField, not a DateField." % self.col.field.name


class DateTime(RefCol):
    """
    Add a datetime selection column.
    """
    allow_nulls = False

    def __init__(self, lookup, kind, tzinfo):
        super(DateTime, self).__init__(lookup)
        self.kind = kind
        self.tzinfo = tzinfo
        if self.tzinfo is None:
            self.tzname = None
        else:
            self.tzname = timezone._get_timezone_name(self.tzinfo)

    def as_sql(self, qn, connection):
        sql, params = self.col.as_sql(qn, connection)
        assert not params, "Params not supported"
        return connection.ops.datetime_trunc_sql(self.kind, sql, self.tzname)

    def add_to_query(self, *args, **kwargs):
        ret = super(DateTime, self).add_to_query(*args, **kwargs)
        self._check_field()
        return ret

    def _check_field(self):
        assert isinstance(self.col.field, DateTimeField), \
            "%r isn't a DateTimeField." % self.col.field.name

    def convert_value(self, value, field, connection):
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
