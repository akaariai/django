from django.db import connections
from django.db.models.query import sql
from django.db.models.sql.constants import QUERY_TERMS

from django.contrib.gis.db.models.fields import GeometryField
from django.contrib.gis.db.models.lookups import GISLookup
from django.contrib.gis.db.models import aggregates as gis_aggregates
from django.contrib.gis.db.models.sql.conversion import GeomField


class GeoQuery(sql.Query):
    """
    A single spatial SQL query.
    """
    # Overriding the valid query terms.
    query_terms = QUERY_TERMS | set(GeometryField.class_lookups.keys())

    #### Methods overridden from the base Query class ####
    def __init__(self, model):
        super(GeoQuery, self).__init__(model)
        self.transformed_srid = None

    def clone(self, *args, **kwargs):
        obj = super(GeoQuery, self).clone(*args, **kwargs)
        obj.transformed_srid = self.transformed_srid
        return obj
