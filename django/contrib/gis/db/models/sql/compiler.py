import datetime

from django.conf import settings
from django.db.backends.utils import truncate_name, typecast_date, typecast_timestamp
from django.db.models.sql import compiler
from django.db.models.sql.constants import MULTI
from django.utils import six
from django.utils.six.moves import zip, zip_longest
from django.utils import timezone

SQLCompiler = compiler.SQLCompiler

class GeoSQLCompiler(compiler.SQLCompiler):

    def setup_converters(self, offset):
        converters = []

        def add_backend_converter(converters, offset, field):
            backend_converter = self.connection.ops.get_field_converter(field)
            if backend_converter:
                converters.append(offset, backend_converter)
        offset = offset + len(self.query.extra_select)
        for i, field in enumerate(self.query.custom_select):
            if hasattr(field, 'convert_value'):
                converters.append((offset + i, field.convert_value))
            add_backend_converter(converters, offset + i, field)
        offset = offset + len(self.query.custom_select)
        only_load = self.deferred_to_columns()
        if self.query.select:
            for col in self.query.select:
                table = col.field.model._meta.db_table
                if table in only_load and col.field.column not in only_load[table]:
                    continue
                if hasattr(col.output_type, 'convert_value'):
                    converters.append((offset, col.output_type.convert_value))
                add_backend_converter(converters, offset, col.output_type)
                offset += 1
            for col in self.query.related_select_cols:
                table = col.field.model._meta.db_table
                if table in only_load and col.field.column not in only_load[table]:
                    continue
                if hasattr(col.output_type, 'convert_value'):
                    converters.append((offset, col.output_type.convert_value))
                add_backend_converter(converters, offset, col.output_type)
                offset += 1
        else:
            def_cols = self.get_default_columns()[0]
            for i, col in enumerate(def_cols):
                if hasattr(col.output_type, 'convert_value'):
                    converters.append((offset + i, col.output_type.convert_value))
                add_backend_converter(converters, offset + i, col.output_type)
            offset += len(def_cols)

        for i, agg in enumerate(self.query.aggregate_select.values()):
            if hasattr(agg.output_type, 'convert_value'):
                converters.append((offset + i, agg.output_type.convert_value))
            add_backend_converter(converters, offset + i, agg.output_type)
        self.converters = converters

    def resolve_columns(self, row, fields=()):
        """
        This routine is necessary so that distances and geometries returned
        from extra selection SQL get resolved appropriately into Python
        objects.
        """
        values = []

        # Have to set a starting row number offset that is used for
        # determining the correct starting row index -- needed for
        # doing pagination with Oracle.
        rn_offset = 0
        if self.connection.ops.oracle:
            if self.query.high_mark is not None or self.query.low_mark:
                rn_offset = 1
        if not hasattr(self, 'converters'):
            self.setup_converters(rn_offset)
        values = list(row)
        for row_pos, converter in self.converters:
            values[row_pos] = converter(row[row_pos], self.connection)
        return tuple(values)

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
        if table_alias is None: table_alias = self.query.get_meta().db_table
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
                    date = typecast_date(str(date))
                if isinstance(date, datetime.datetime):
                    date = date.date()
                yield date

class SQLDateTimeCompiler(compiler.SQLDateTimeCompiler, GeoSQLCompiler):
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
                datetime = row[offset]
                if self.connection.ops.oracle:
                    datetime = self.resolve_columns(row, fields)[offset]
                elif needs_string_cast:
                    datetime = typecast_timestamp(str(datetime))
                # Datetimes are artifically returned in UTC on databases that
                # don't support time zone. Restore the zone used in the query.
                if settings.USE_TZ:
                    datetime = datetime.replace(tzinfo=None)
                    datetime = timezone.make_aware(datetime, self.query.tzinfo)
                yield datetime
