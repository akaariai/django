"""
Useful auxilliary data structures for query construction. Not useful outside
the SQL domain.
"""
# TODO: move Col here.
from django.db.models.lookups import Col


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


class DateTime(Col):
    """
    Add a datetime selection column.
    """
    def __init__(self, alias, field, lookup_type, tzname):
        super(DateTime, self).__init__(alias, field)
        self.lookup_type = lookup_type
        self.tzname = tzname

    def relabeled_clone(self, change_map):
        return self.__class__(
            change_map.get(self.alias, self.alias), self.field,
            self.lookup_type, self.tzname
        )

    def as_sql(self, qn, connection):
        col, params = super(DateTime, self).as_sql(qn, connection)
        assert not params, "Params not supported"
        return connection.ops.datetime_trunc_sql(self.lookup_type, col, self.tzname)
