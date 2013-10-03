"""
Lookups for GeoFields. The implementation was adapted directly from
GeoWhereNode when custom lookups were implemented. Rewrite to better use
standard custom lookups features wouldn't be a bad idea.
"""
from django.contrib.gis.db.models.fields import GeometryField
from django.db.models.constants import LOOKUP_SEP
from django.db.models.fields import FieldDoesNotExist
from django.db.models.lookups import SimpleLookup
from django.db.models.sql.expressions import SQLEvaluator

class GeoLookup(SimpleLookup):

    def as_sql(self, qn, connection):
        lhs, lhs_params = self.process_lhs(qn, connection)
        assert not lhs_params
        value = self.value
        if isinstance(value, SQLEvaluator):
            geo_fld = self._check_geo_field(value.opts, value.expression.name)
            if not geo_fld:
                raise ValueError('No geographic field found in expression.')
            value.srid = geo_fld.srid
        db_type = self.field.db_type(connection=connection)
        field_params = self.field.get_db_prep_lookup(self.lookup_type, value, connection=connection)
        sql, params = connection.ops.spatial_lookup_sql(
            (lhs, db_type), self.lookup_type, value, self.field, qn)
        return sql, params + field_params

    @classmethod
    def _check_geo_field(cls, opts, lookup):
        """
        Utility for checking the given lookup with the given model options.
        The lookup is a string either specifying the geographic field, e.g.
        'point, 'the_geom', or a related lookup on a geographic field like
        'address__point'.

        If a GeometryField exists according to the given lookup on the model
        options, it will be returned.  Otherwise returns None.
        """
        # This takes into account the situation where the lookup is a
        # lookup to a related geographic field, e.g., 'address__point'.
        field_list = lookup.split(LOOKUP_SEP)

        # Reversing so list operates like a queue of related lookups,
        # and popping the top lookup.
        field_list.reverse()
        fld_name = field_list.pop()

        try:
            geo_fld = opts.get_field(fld_name)
            # If the field list is still around, then it means that the
            # lookup was for a geometry field across a relationship --
            # thus we keep on getting the related model options and the
            # model field associated with the next field in the list
            # until there's no more left.
            while len(field_list):
                opts = geo_fld.rel.to._meta
                geo_fld = opts.get_field(field_list.pop())
        except (FieldDoesNotExist, AttributeError):
            return False

        # Finally, make sure we got a Geographic field and return.
        if isinstance(geo_fld, GeometryField):
            return geo_fld
        else:
            return False

ALL_TERMS = [
    'bbcontains', 'bboverlaps', 'contained', 'contains',
    'contains_properly', 'coveredby', 'covers', 'crosses', 'disjoint',
    'distance_gt', 'distance_gte', 'distance_lt', 'distance_lte',
    'dwithin', 'equals', 'exact',
    'intersects', 'overlaps', 'relate', 'same_as', 'touches', 'within',
    'left', 'right', 'overlaps_left', 'overlaps_right',
    'overlaps_above', 'overlaps_below',
    'strictly_above', 'strictly_below'
]

for term in ALL_TERMS:
    term_lookup = type(term, (GeoLookup,), {'lookup_type': term})
    GeometryField.register_class_lookup(term_lookup)
