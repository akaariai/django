"""
Constants specific to the SQL storage portion of the ORM.
"""

from collections import namedtuple
import re

# Valid query types (a set is used for speedy lookups). These are (currently)
# considered SQL-specific; other storage systems may choose to use different
# lookup types.
QUERY_TERMS = set([
    # There is nothing to see here. All the lookups are implemented by Field.
])

# Size of each "chunk" for get_iterator calls.
# Larger values are slightly faster at the expense of more storage space.
GET_ITERATOR_CHUNK_SIZE = 100

# Constants to make looking up tuple values clearer.
# Join lists (indexes into the tuples that are values in the alias_map
# dictionary in the Query class).
JoinInfo = namedtuple('JoinInfo',
                      'table_name rhs_alias join_type lhs_alias '
                      'lhs_join_col rhs_join_col nullable extra')
# JoinPath is used when converting lookups (fk__somecol). The contents
# describe the join in Model terms (model Options and Fields for both
# sides of the join. In addition contains extra join restrictions, used
# by generic relations for example. This is a tuple of (col, someval),
# where col is a column on the to side. A join condition like
#    ON from.field = to.field AND to.col = someval
# will be generated for the join.
JoinPath = namedtuple('JoinPath',
                      'from_field to_field from_opts to_opts direction extra')

# Pairs of column clauses to select, and (possibly None) field for the clause.
SelectInfo = namedtuple('SelectInfo', 'col field')

# How many results to expect from a cursor.execute call
MULTI = 'multi'
SINGLE = 'single'

ORDER_PATTERN = re.compile(r'\?|[-+]?[.\w]+$')
ORDER_DIR = {
    'ASC': ('ASC', 'DESC'),
    'DESC': ('DESC', 'ASC'),
}

# A marker for join-reusability.
REUSE_ALL = object()
