from django.db.models import Aggregate

class GeoAggregate(Aggregate):
    def add_to_query(self, query, alias, col, source, is_summary):
        try:
            aggregate = super(GeoAggregate, self).add_to_query(
                query, alias, col, source, is_summary)
        except AttributeError:
            from django.contrib.gis.db.models.sql import aggregates
            klass = getattr(aggregates, self.name)
            aggregate = klass(col, source=source, is_summary=is_summary, **self.extra)
        return aggregate


class Collect(GeoAggregate):
    name = 'Collect'

class Extent(GeoAggregate):
    name = 'Extent'

class Extent3D(GeoAggregate):
    name = 'Extent3D'

class MakeLine(GeoAggregate):
    name = 'MakeLine'

class Union(GeoAggregate):
    name = 'Union'
