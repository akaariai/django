from datetime import datetime
from itertools import repeat

from django.db.models.sql.datastructures import Constraint
from django.db.models.sql.where import EmptyShortCircuit, EmptyResultSet
from django.db.models.sql.aggregates import Aggregate
from django.utils.six.moves import xrange


class Lookup(object):
    """
    Lookup is to be used in queries. Don't know how, don't know
    when...
    """
    lookup_name = None

    def make_atom(self, lvalue, value_annotation, params_or_value, qn, connection):
        if isinstance(lvalue, Constraint):
            try:
                lvalue, params = lvalue.process(self, params_or_value, connection)
            except EmptyShortCircuit:
                raise EmptyResultSet
        elif isinstance(lvalue, Aggregate):
            params = lvalue.field.get_db_prep_lookup(self.lookup_name, params_or_value, connection)
        else:
            raise TypeError("'make_atom' expects a Constraint or an Aggregate "
                            "as the first item of its 'child' argument.")

        if isinstance(lvalue, tuple):
            # A direct database column lookup.
            field_sql = self.sql_for_columns(lvalue, qn, connection)
        else:
            # A smart object with an as_sql() method.
            field_sql = lvalue.as_sql(qn, connection)

        if value_annotation is datetime:
            cast_sql = connection.ops.datetime_cast_sql()
        else:
            cast_sql = '%s'

        if hasattr(params, 'as_sql'):
            extra, params = params.as_sql(qn, connection)
            cast_sql = ''
        else:
            extra = ''

        if (len(params) == 1 and params[0] == '' and self.lookup_name == 'exact'
            and connection.features.interprets_empty_strings_as_nulls):
            self.lookup_name = 'isnull'
            value_annotation = True

        if self.lookup_name in connection.operators:
            format = "%s %%s %%s" % (connection.ops.lookup_cast(self.lookup_name),)
            return (format % (field_sql,
                              connection.operators[self.lookup_name] % cast_sql,
                              extra), params)

        return self.as_sql(field_sql, value_annotation, extra, params, connection, cast_sql)

    def as_sql(self, field_sql, value_annotation, extra, params, connection, cast_sql):
        if self.lookup_name == 'in':
            if not value_annotation:
                raise EmptyResultSet
            if extra:
                return ('%s IN %s' % (field_sql, extra), params)
            max_in_list_size = connection.ops.max_in_list_size()
            if max_in_list_size and len(params) > max_in_list_size:
                # Break up the params list into an OR of manageable chunks.
                in_clause_elements = ['(']
                for offset in xrange(0, len(params), max_in_list_size):
                    if offset > 0:
                        in_clause_elements.append(' OR ')
                    in_clause_elements.append('%s IN (' % field_sql)
                    group_size = min(len(params) - offset, max_in_list_size)
                    param_group = ', '.join(repeat('%s', group_size))
                    in_clause_elements.append(param_group)
                    in_clause_elements.append(')')
                in_clause_elements.append(')')
                return ''.join(in_clause_elements), params
            else:
                return ('%s IN (%s)' % (field_sql,
                                        ', '.join(repeat('%s', len(params)))),
                        params)
        elif self.lookup_name in ('range', 'year'):
            return ('%s BETWEEN %%s and %%s' % field_sql, params)
        elif self.lookup_name in ('month', 'day', 'week_day'):
            return ('%s = %%s' % connection.ops.date_extract_sql(self.lookup_name, field_sql),
                    params)
        elif self.lookup_name == 'isnull':
            return ('%s IS %sNULL' % (field_sql,
                (not value_annotation and 'NOT ' or '')), ())
        elif self.lookup_name == 'search':
            return (connection.ops.fulltext_search_sql(field_sql), params)
        elif self.lookup_name in ('regex', 'iregex'):
            return connection.ops.regex_lookup(self.lookup_name) % (field_sql, cast_sql), params

        raise TypeError('Invalid lookup_type: %r' % self.lookup_name)
    
    def sql_for_columns(self, data, qn, connection):
        """
        Returns the SQL fragment used for the left-hand side of a column
        constraint (for example, the "T1.foo" portion in the clause
        "WHERE ... T1.foo = 6").
        """
        table_alias, name, db_type = data
        if table_alias:
            lhs = '%s.%s' % (qn(table_alias), qn(name))
        else:
            lhs = qn(name)
        return connection.ops.field_cast_sql(db_type) % lhs

    def get_prep_lookup(self, field, value):
        return field.get_prep_lookup(self.lookup_name, value)

    def get_db_prep_lookup(self, field, value, connection, prepared=False):
        """
        Returns a tuple of data suitable for inclusion in a WhereNode
        instance.
        """
        # Because of circular imports, we need to import this here.
        params = field.get_db_prep_lookup(self.lookup_name, value,
            connection=connection, prepared=prepared)
        db_type = field.db_type(connection=connection)
        return params, db_type


class BackwardsCompatLookup(Lookup):
    def __init__(self, lookup_name):
        self.lookup_name = lookup_name
