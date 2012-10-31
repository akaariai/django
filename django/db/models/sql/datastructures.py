"""
Useful auxilliary data structures for query construction. Not useful outside
the SQL domain.
"""

class EmptyResultSet(Exception):
    pass

class Empty(object):
    pass

class RawValue(object):
    def __init__(self, value):
        self.value = value

class Date(object):
    """
    Add a date selection column.
    """
    def __init__(self, col, lookup_type):
        self.col = col
        self.lookup_type = lookup_type

    def relabel_aliases(self, change_map):
        c = self.col
        if isinstance(c, (list, tuple)):
            self.col = (change_map.get(c[0], c[0]), c[1])

    def as_sql(self, qn, connection):
        if isinstance(self.col, (list, tuple)):
            col = '%s.%s' % tuple([qn(c) for c in self.col])
        else:
            col = self.col
        return connection.ops.date_trunc_sql(self.lookup_type, col)
