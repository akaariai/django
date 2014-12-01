"""
This module holds simple classes to convert geospatial values from the
database.
"""

from django.contrib.gis.geometry.backend import Geometry
from django.contrib.gis.measure import Area, Distance
from django.contrib.gis.db.models.fields import GeoSelectFormatMixin


class BaseField(object):
    empty_strings_allowed = True

    def get_db_converters(self, connection):
        return [self.from_db_value]

    def select_format(self, compiler, sql, params):
        return sql, params


class AreaField(BaseField):
    "Wrapper for Area values."
    def __init__(self, area_att):
        self.area_att = area_att

    def from_db_value(self, value, connection):
        if value is not None:
            value = Area(**{self.area_att: value})
        return value

    def get_internal_type(self):
        return 'AreaField'


class DistanceField(BaseField):
    "Wrapper for Distance values."
    def __init__(self, distance_att):
        self.distance_att = distance_att

    def from_db_value(self, value, connection):
        if value is not None:
            value = Distance(**{self.distance_att: value})
        return value

    def get_internal_type(self):
        return 'DistanceField'


class GeomField(GeoSelectFormatMixin, BaseField):
    """
    Wrapper for Geometry values.  It is a lightweight alternative to
    using GeometryField (which requires an SQL query upon instantiation).
    """
    def from_db_value(self, value, connection):
        if value is not None:
            value = Geometry(value)
        return value

    def get_internal_type(self):
        return 'GeometryField'

    def select_format(self, compiler, sql, params):
        """
        Returns the selection format string, depending on the requirements
        of the spatial backend.  For example, Oracle and MySQL require custom
        selection formats in order to retrieve geometries in OGC WKT. For all
        other fields a simple '%s' format string is returned.
        """
        connection = compiler.connection
        query = compiler.query
        if connection.ops.select:
            # This allows operations to be done on fields in the SELECT,
            # overriding their values -- used by the Oracle and MySQL
            # spatial backends to get database values as WKT, and by the
            # `transform` method.
            sel_fmt = connection.ops.select

            # Because WKT doesn't contain spatial reference information,
            # the SRID is prefixed to the returned WKT to ensure that the
            # transformed geometries have an SRID different than that of the
            # field -- this is only used by `transform` for Oracle and
            # SpatiaLite backends.
            if query and query.get_context('transformed_srid') and (
                    connection.ops.oracle or connection.ops.spatialite):
                sel_fmt = "'SRID=%d;'||%s" % (query.get_context('transformed_srid'), sel_fmt)
        else:
            if query and query.get_context('transformed_srid'):
                sel_fmt = '%s(%%s, %s)' % (connection.ops.transform, query.get_context('transformed_srid'))
            else:
                sel_fmt = '%s'
        return sel_fmt % sql, params


class GMLField(BaseField):
    """
    Wrapper for GML to be used by Oracle to ensure Database.LOB conversion.
    """

    def get_internal_type(self):
        return 'GMLField'

    def from_db_value(self, value, connection):
        return value
