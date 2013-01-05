try:
    from itertools import zip_longest
except ImportError:
    from itertools import izip_longest as zip_longest

from django.utils.six.moves import zip

from django.db.backends.util import typecast_timestamp
from django.db.models.sql import compiler
from django.db.models.sql.constants import MULTI

SQLCompiler = compiler.SQLCompiler

class GeoSQLCompiler(compiler.SQLCompiler):

    def resolve_columns(self, row, fields=()):
        """
        This routine is necessary so that distances and geometries returned
        from extra selection SQL get resolved appropriately into Python
        objects.
        """
        values = []
        aliases = list(self.query.extra_select)

        # Have to set a starting row number offset that is used for
        # determining the correct starting row index -- needed for
        # doing pagination with Oracle.
        rn_offset = 0
        if self.connection.ops.oracle:
            if self.query.high_mark is not None or self.query.low_mark: rn_offset = 1
        index_start = rn_offset + len(aliases)

        # Converting any extra selection values (e.g., geometries and
        # distance objects added by GeoQuerySet methods).
        values = [self.query.convert_values(v,
                               self.query.extra_select_fields.get(a, None),
                               self.connection)
                  for v, a in zip(row[rn_offset:index_start], aliases)]
        if self.connection.ops.oracle or getattr(self.query, 'geo_values', False):
            # We resolve the rest of the columns if we're on Oracle or if
            # the `geo_values` attribute is defined.
            for value, field in zip_longest(row[index_start:], fields):
                values.append(self.query.convert_values(value, field, self.connection))
        else:
            values.extend(row[index_start:])
        return tuple(values)

    #### Routines unique to GeoQuery ####
    def get_extra_select_format(self, alias):
        sel_fmt = '%s'
        if hasattr(self.query, 'custom_select') and alias in self.query.custom_select:
            sel_fmt = sel_fmt % self.query.custom_select[alias]
        return sel_fmt

    def get_field_select(self, field, alias=None, column=None):
        """
        Returns the SELECT SQL string for the given field.  Figures out
        if any custom selection SQL is needed for the column  The `alias`
        keyword may be used to manually specify the database table where
        the column exists, if not in the model associated with this
        `GeoQuery`.  Similarly, `column` may be used to specify the exact
        column name, rather than using the `column` attribute on `field`.
        """
        sel_fmt = self.get_select_format(field)
        if field in self.query.custom_select:
            field_sel = sel_fmt % self.query.custom_select[field]
        else:
            field_sel = sel_fmt % self._field_column(field, alias, column)
        return field_sel

    def get_select_format(self, fld):
        """
        Returns the selection format string, depending on the requirements
        of the spatial backend.  For example, Oracle and MySQL require custom
        selection formats in order to retrieve geometries in OGC WKT. For all
        other fields a simple '%s' format string is returned.
        """
        if self.connection.ops.select and hasattr(fld, 'geom_type'):
            # This allows operations to be done on fields in the SELECT,
            # overriding their values -- used by the Oracle and MySQL
            # spatial backends to get database values as WKT, and by the
            # `transform` method.
            sel_fmt = self.connection.ops.select

            # Because WKT doesn't contain spatial reference information,
            # the SRID is prefixed to the returned WKT to ensure that the
            # transformed geometries have an SRID different than that of the
            # field -- this is only used by `transform` for Oracle and
            # SpatiaLite backends.
            if self.query.transformed_srid and ( self.connection.ops.oracle or
                                                 self.connection.ops.spatialite ):
                sel_fmt = "'SRID=%d;'||%s" % (self.query.transformed_srid, sel_fmt)
        else:
            sel_fmt = '%s'
        return sel_fmt

    # Private API utilities, subject to change.
    def _field_column(self, field, table_alias=None, column=None):
        """
        Helper function that returns the database column for the given field.
        The table and column are returned (quoted) in the proper format, e.g.,
        `"geoapp_city"."point"`.  If `table_alias` is not specified, the
        database table associated with the model of this `GeoQuery` will be
        used.  If `column` is specified, it will be used instead of the value
        in `field.column`.
        """
        if table_alias is None: table_alias = self.query.model._meta.db_table
        return "%s.%s" % (self.quote_name_unless_alias(table_alias),
                          self.connection.ops.quote_name(column or field.column))

class SQLInsertCompiler(compiler.SQLInsertCompiler, GeoSQLCompiler):
    pass

class SQLDeleteCompiler(compiler.SQLDeleteCompiler, GeoSQLCompiler):
    pass

class SQLUpdateCompiler(compiler.SQLUpdateCompiler, GeoSQLCompiler):
    pass

class SQLAggregateCompiler(compiler.SQLAggregateCompiler, GeoSQLCompiler):
    pass

class SQLDateCompiler(compiler.SQLDateCompiler, GeoSQLCompiler):
    """
    This is overridden for GeoDjango to properly cast date columns, since
    `GeoQuery.resolve_columns` is used for spatial values.
    See #14648, #16757.
    """
    def results_iter(self):
        if self.connection.ops.oracle:
            from django.db.models.fields import DateTimeField
            fields = [DateTimeField()]
        else:
            needs_string_cast = self.connection.features.needs_datetime_string_cast

        offset = len(self.query.extra_select)
        for rows in self.execute_sql(MULTI):
            for row in rows:
                date = row[offset]
                if self.connection.ops.oracle:
                    date = self.resolve_columns(row, fields)[offset]
                elif needs_string_cast:
                    date = typecast_timestamp(str(date))
                yield date
