from django.db.models.query import sql

from django.contrib.gis.db.models.fields import GeometryField
from django.contrib.gis.db.models.sql import aggregates as gis_aggregates
from django.contrib.gis.db.models.lookups import GeoLookup

class GeoQuery(sql.Query):
    """
    A single spatial SQL query.
    """
    # Overridding the valid query terms.
    aggregates_module = gis_aggregates

    compiler = 'GeoSQLCompiler'

    #### Methods overridden from the base Query class ####
    def __init__(self, *args, **kwargs):
        super(GeoQuery, self).__init__(*args, **kwargs)
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
            return GeoLookup._check_geo_field(self.model._meta, field_name)
