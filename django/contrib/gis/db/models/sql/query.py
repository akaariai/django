from django.db.models.query import sql

from django.contrib.gis.db.models.sql import aggregates as gis_aggregates

class GeoQuery(sql.Query):
    """
    A single spatial SQL query.
    """
    # Overridding the valid query terms.
    aggregates_module = gis_aggregates

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
