from collections import namedtuple
import re

# Valid query types (a dictionary is used for speedy lookups).
QUERY_TERMS = set([
    'exact', 'iexact', 'contains', 'icontains', 'gt', 'gte', 'lt', 'lte', 'in',
    'startswith', 'istartswith', 'endswith', 'iendswith', 'range', 'year',
    'month', 'day', 'week_day', 'isnull', 'search', 'regex', 'iregex',
])

# Size of each "chunk" for get_iterator calls.
# Larger values are slightly faster at the expense of more storage space.
GET_ITERATOR_CHUNK_SIZE = 100

# Separator used to split filter strings apart.
LOOKUP_SEP = '__'

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

# How many results to expect from a cursor.execute call
MULTI = 'multi'
SINGLE = 'single'

ORDER_PATTERN = re.compile(r'\?|[-+]?[.\w]+$')
ORDER_DIR = {
    'ASC': ('ASC', 'DESC'),
    'DESC': ('DESC', 'ASC'),
}
