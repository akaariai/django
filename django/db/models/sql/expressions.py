from django.core.exceptions import FieldError
from django.db.models.constants import LOOKUP_SEP
from django.db.models.fields import FieldDoesNotExist
import copy

class SQLEvaluator(object):
    def __init__(self, expression, query, allow_joins=True, reuse=None):
        self.expression = expression
        self.opts = query.get_meta()
        self.reuse = reuse
        self.cols = []
        self.expression.prepare(self, query, allow_joins)

    def relabeled_clone(self, change_map):
        clone = copy.copy(self)
        clone.cols = []
        for node, col in self.cols:
            if hasattr(col, 'relabeled_clone'):
                clone.cols.append((node, col.relabeled_clone(change_map)))
            else:
                clone.cols.append((node,
                                   (change_map.get(col[0], col[0]), col[1])))
        return clone

    def get_cols(self):
        cols = []
        for node, col in self.cols:
            if hasattr(node, 'get_cols'):
                cols.extend(node.get_cols())
            elif isinstance(col, tuple):
                cols.append(col)
        return cols

    def prepare(self):
        return self

    def as_sql(self, qn, connection):
        return self.expression.evaluate(self, qn, connection)

    #####################################################
    # Vistor methods for initial expression preparation #
    #####################################################

    def prepare_node(self, node, query, allow_joins):
        for child in node.children:
            if hasattr(child, 'prepare'):
                child.prepare(self, query, allow_joins)

    def prepare_leaf(self, node, query, allow_joins):
        self.cols.append((node, query.resolve_ref(node.name, reuse=self.reuse,
                                                  allow_joins=allow_joins)))

    ##################################################
    # Vistor methods for final expression evaluation #
    ##################################################

    def evaluate_node(self, node, qn, connection):
        expressions = []
        expression_params = []
        for child in node.children:
            if hasattr(child, 'evaluate'):
                sql, params = child.evaluate(self, qn, connection)
            else:
                sql, params = '%s', (child,)

            if len(getattr(child, 'children', [])) > 1:
                format = '(%s)'
            else:
                format = '%s'

            if sql:
                expressions.append(format % sql)
                expression_params.extend(params)

        return connection.ops.combine_expression(node.connector, expressions), expression_params

    def evaluate_leaf(self, node, qn, connection):
        col = None
        for n, c in self.cols:
            if n is node:
                col = c
                break
        if col is None:
            raise ValueError("Given node not found")
        if hasattr(col, 'as_sql'):
            return col.as_sql(qn, connection)
        else:
            return '%s.%s' % (qn(col[0]), qn(col[1])), []

    def evaluate_date_modifier_node(self, node, qn, connection):
        timedelta = node.children.pop()
        sql, params = self.evaluate_node(node, qn, connection)

        if timedelta.days == 0 and timedelta.seconds == 0 and \
                timedelta.microseconds == 0:
            return sql, params

        return connection.ops.date_interval_sql(sql, node.connector, timedelta), params
