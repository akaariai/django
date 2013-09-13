from django.db.models.query import sql

from django.contrib.gis.db.models.fields import GeometryField
from django.contrib.gis.db.models.sql import aggregates as gis_aggregates
from django.contrib.gis.db.models.sql.conversion import AreaField, DistanceField, GeomField
from django.contrib.gis.db.models.sql.where import GeoWhereNode
from django.contrib.gis.geometry.backend import Geometry
from django.contrib.gis.measure import Area, Distance


ALL_TERMS = set([
            'bbcontains', 'bboverlaps', 'contained', 'contains',
            'contains_properly', 'coveredby', 'covers', 'crosses', 'disjoint',
            'distance_gt', 'distance_gte', 'distance_lt', 'distance_lte',
            'dwithin', 'equals', 'exact',
            'intersects', 'overlaps', 'relate', 'same_as', 'touches', 'within',
            'left', 'right', 'overlaps_left', 'overlaps_right',
            'overlaps_above', 'overlaps_below',
            'strictly_above', 'strictly_below'
            ])
ALL_TERMS.update(sql.constants.QUERY_TERMS)

class GeoQuery(sql.Query):
    """
    A single spatial SQL query.
    """
    # Overridding the valid query terms.
    query_terms = ALL_TERMS
    aggregates_module = gis_aggregates

    compiler = 'GeoSQLCompiler'

    #### Methods overridden from the base Query class ####
    def __init__(self, model, where=GeoWhereNode):
        super(GeoQuery, self).__init__(model, where)
        # The following attributes are customized for the GeoQuerySet.
        # The GeoWhereNode and SpatialBackend classes contain backend-specific
        # routines and functions.
        self.transformed_srid = None

    def clone(self, *args, **kwargs):
        obj = super(GeoQuery, self).clone(*args, **kwargs)
        # Customized selection dictionary and transformed srid flag have
        # to also be added to obj.
        obj.transformed_srid = self.transformed_srid
        return obj

    def resolve_aggregate(self, value, aggregate, connection):
        """
        Overridden from GeoQuery's normalize to handle the conversion of
        GeoAggregate objects.
        """
        if isinstance(aggregate, self.aggregates_module.GeoAggregate):
            if aggregate.is_extent:
                if aggregate.is_extent == '3D':
                    return connection.ops.convert_extent3d(value)
                else:
                    return connection.ops.convert_extent(value)
            else:
                return connection.ops.convert_geom(value, aggregate.source)
        else:
            return super(GeoQuery, self).resolve_aggregate(value, aggregate, connection)

    # Private API utilities, subject to change.
    def _geo_field(self, field_name=None):
        """
        Returns the first Geometry field encountered; or specified via the
        `field_name` keyword.  The `field_name` may be a string specifying
        the geometry field on this GeoQuery's model, or a lookup string
        to a geometry field via a ForeignKey relation.
        """
        if field_name is None:
            # Incrementing until the first geographic field is found.
            for fld in self.model._meta.fields:
                if isinstance(fld, GeometryField): return fld
            return False
        else:
            # Otherwise, check by the given field name -- which may be
            # a lookup to a _related_ geographic field.
            return GeoWhereNode._check_geo_field(self.model._meta, field_name)
