from django.db.models.aggregates import Aggregate
from django.contrib.gis.db.models.fields import GeometryField

__all__ = ['Collect', 'Extent', 'Extent3D', 'MakeLine', 'Union']


class GeoAggregate(Aggregate):
    template = None
    function = None
    is_extent = False
    conversion_class = None  # TODO: is this still used?

    def as_sql(self, compiler, connection):
        if connection.ops.oracle:
            if not hasattr(self, 'tolerance'):
                self.tolerance = 0.05
            self.extra['tolerance'] = self.tolerance

        template, function = connection.ops.spatial_aggregate_sql(self)
        if template is None:
            template = '%(function)s(%(expressions)s)'
        self.extra['template'] = self.extra.get('template', template)
        self.extra['function'] = self.extra.get('function', function)
        return super(GeoAggregate, self).as_sql(compiler, connection)

    def prepare(self, query=None, allow_joins=True, reuse=None, summarise=False):
        self.is_summary = summarise
        super(GeoAggregate, self).prepare(query, allow_joins, reuse)
        if not isinstance(self.expression.output_type, GeometryField):
            raise ValueError('Geospatial aggregates only allowed on geometry fields.')


class Collect(GeoAggregate):
    name = 'Collect'


class Extent(GeoAggregate):
    name = 'Extent'
    is_extent = '2D'


class Extent3D(GeoAggregate):
    name = 'Extent3D'
    is_extent = '3D'


class MakeLine(GeoAggregate):
    name = 'MakeLine'


class Union(GeoAggregate):
    name = 'Union'
