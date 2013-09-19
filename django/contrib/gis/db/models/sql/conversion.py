"""
This module holds simple classes used by GeoQuery.convert_values
to convert geospatial values from the database.
"""
from django.contrib.gis.measure import Area, Distance
from django.contrib.gis.geometry.backend import Geometry

class BaseField(object):
    empty_strings_allowed = True

    def get_internal_type(self):
        "Overloaded method so OracleQuery.convert_values doesn't balk."
        return None

class AreaField(BaseField):
    "Wrapper for Area values."
    def __init__(self, area_att):
        self.area_att = area_att

    def convert_value(self, value, field, connection):
        return Area(**{self.area_att: value})

class DistanceField(BaseField):
    "Wrapper for Distance values."
    def __init__(self, distance_att):
        self.distance_att = distance_att

    def convert_value(self, value, field, connection):
        return Distance(**{self.distance_att: value})

class GeomField(BaseField):
    """
    Wrapper for Geometry values.  It is a lightweight alternative to
    using GeometryField (which requires a SQL query upon instantiation).
    """
    def convert_value(self, value, field, connection):
        return Geometry(value) if value else value
