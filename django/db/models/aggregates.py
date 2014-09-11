"""
Classes to represent the definitions of aggregate functions.
"""
from django.core.exceptions import FieldError
from django.db.models.expressions import Func, Value, Ref
from django.db.models.fields import IntegerField, FloatField

__all__ = [
    'Aggregate', 'Avg', 'Count', 'Max', 'Min', 'StdDev', 'Sum', 'Variance',
]


class Aggregate(Func):
    is_aggregate = True
    name = None

    def __init__(self, expression, output_field=None, **extra):
        super(Aggregate, self).__init__(expression, output_field=output_field, **extra)
        assert len(self.source_expressions) == 1
        if self.source_expressions[0].is_aggregate:
            raise FieldError("Cannot compute %s(%s(..)): aggregates cannot be nested" % (
                self.name, expression.name))

    def prepare(self, query=None, allow_joins=True, reuse=None, summarize=False):
        c = super(Aggregate, self).prepare(query, allow_joins, reuse, summarize)
        if hasattr(c.source_expressions[0], 'name'):  # simple lookup
            c.source_expressions[0] = c.source_expressions[0].copy()
            expr = c.source_expressions[0]
            name = expr.name
            reffed, _ = expr.contains_aggregate(query.annotations)
            if reffed and not c.is_summary:
                raise FieldError("Cannot compute %s('%s'): '%s' is an aggregate" % (
                    c.name, name, name))
            if name in query.annotations:
                annotation = query.annotations[name]
                if c._output_field is None:
                    c._output_field = annotation.output_field
                if c.is_summary:
                    # force subquery relabel
                    expr.col = Ref(name, annotation)
                    return c
        c._patch_aggregate(query)  # backward-compatibility support
        return c

    def refs_field(self, aggregate_types, field_types):
        try:
            return (isinstance(self, aggregate_types) and
                    isinstance(self.source._output_field_or_none, field_types))
        except FieldError:
            # Sometimes we don't know the source's output type (for example,
            # doing Sum(F('datetimefield') + F('datefield'), output_type=DateTimeField())
            # is OK, but the Expression(F('datetimefield') + F('datefield')) doesn't
            # have any output field.
            return False

    @property
    def source(self):
        return self.source_expressions[0]

    @property
    def default_alias(self):
        if hasattr(self.source_expressions[0], 'name'):
            return '%s__%s' % (self.source_expressions[0].name, self.name.lower())
        raise TypeError("Complex expressions require an alias")

    def get_group_by_cols(self):
        return []

    def _patch_aggregate(self, query):
        """
        Helper method for patching 3rd party aggregates that do not yet support
        the new way of subclassing. This method should be removed in 2.0

        add_to_query(query, alias, col, source, is_summary) will be defined on
        legacy aggregates which, in turn, instantiates the SQL implementation of
        the aggregate. In all the cases found, the general implementation of
        add_to_query looks like:

        def add_to_query(self, query, alias, col, source, is_summary):
            klass = SQLImplementationAggregate
            aggregate = klass(col, source=source, is_summary=is_summary, **self.extra)
            query.aggregates[alias] = aggregate

        By supplying a known alias, we can get the SQLAggregate out of the
        aggregates dict, and use the sql_function and sql_template attributes
        to patch *this* aggregate.
        """
        if not hasattr(self, 'add_to_query') or self.function is not None:
            return

        placeholder_alias = "_XXXXXXXX_"
        self.add_to_query(query, placeholder_alias, None, None, None)
        sql_aggregate = query.aggregates.pop(placeholder_alias)
        if 'sql_function' not in self.extra and hasattr(sql_aggregate, 'sql_function'):
            self.extra['function'] = sql_aggregate.sql_function

        if hasattr(sql_aggregate, 'sql_template'):
            self.extra['template'] = sql_aggregate.sql_template


class Avg(Aggregate):
    function = 'AVG'
    name = 'Avg'

    def __init__(self, expression, **extra):
        super(Avg, self).__init__(expression, output_field=FloatField(), **extra)

    def convert_value(self, value, connection):
        if value is None:
            return value
        return float(value)


class Count(Aggregate):
    function = 'COUNT'
    name = 'Count'
    template = '%(function)s(%(distinct)s%(expressions)s)'

    def __init__(self, expression, distinct=False, **extra):
        if expression == '*':
            expression = Value(expression)
            expression._output_field = IntegerField()
        super(Count, self).__init__(
            expression, distinct='DISTINCT ' if distinct else '', output_field=IntegerField(), **extra)

    def convert_value(self, value, connection):
        if value is None:
            return 0
        return int(value)


class Max(Aggregate):
    function = 'MAX'
    name = 'Max'


class Min(Aggregate):
    function = 'MIN'
    name = 'Min'


class StdDev(Aggregate):
    name = 'StdDev'

    def __init__(self, expression, sample=False, **extra):
        self.function = 'STDDEV_SAMP' if sample else 'STDDEV_POP'
        super(StdDev, self).__init__(expression, output_field=FloatField(), **extra)

    def convert_value(self, value, connection):
        if value is None:
            return value
        return float(value)


class Sum(Aggregate):
    function = 'SUM'
    name = 'Sum'


class Variance(Aggregate):
    name = 'Variance'

    def __init__(self, expression, sample=False, **extra):
        self.function = 'VAR_SAMP' if sample else 'VAR_POP'
        super(Variance, self).__init__(expression, output_field=FloatField(), **extra)

    def convert_value(self, value, connection):
        if value is None:
            return value
        return float(value)
