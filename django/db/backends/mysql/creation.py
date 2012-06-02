from django.db import QName
from django.db.backends.creation import BaseDatabaseCreation

class DatabaseCreation(BaseDatabaseCreation):
    # This dictionary maps Field objects to their associated MySQL column
    # types, as strings. Column-type strings can contain format strings; they'll
    # be interpolated against the values of Field.__dict__ before being output.
    # If a column type is set to None, it won't be included in the output.
    data_types = {
        'AutoField':         'integer AUTO_INCREMENT',
        'BooleanField':      'bool',
        'CharField':         'varchar(%(max_length)s)',
        'CommaSeparatedIntegerField': 'varchar(%(max_length)s)',
        'DateField':         'date',
        'DateTimeField':     'datetime',
        'DecimalField':      'numeric(%(max_digits)s, %(decimal_places)s)',
        'FileField':         'varchar(%(max_length)s)',
        'FilePathField':     'varchar(%(max_length)s)',
        'FloatField':        'double precision',
        'IntegerField':      'integer',
        'BigIntegerField':   'bigint',
        'IPAddressField':    'char(15)',
        'GenericIPAddressField': 'char(39)',
        'NullBooleanField':  'bool',
        'OneToOneField':     'integer',
        'PositiveIntegerField': 'integer UNSIGNED',
        'PositiveSmallIntegerField': 'smallint UNSIGNED',
        'SlugField':         'varchar(%(max_length)s)',
        'SmallIntegerField': 'smallint',
        'TextField':         'longtext',
        'TimeField':         'time',
    }

    def sql_table_creation_suffix(self):
        suffix = []
        if self.connection.settings_dict['TEST_CHARSET']:
            suffix.append('CHARACTER SET %s' % self.connection.settings_dict['TEST_CHARSET'])
        if self.connection.settings_dict['TEST_COLLATION']:
            suffix.append('COLLATE %s' % self.connection.settings_dict['TEST_COLLATION'])
        return ' '.join(suffix)

    def sql_for_inline_foreign_key_references(self, field, known_models, style):
        "All inline references are pending under MySQL"
        return [], True

    def sql_for_inline_many_to_many_references(self, model, field, style):
        from django.db import models
        opts = model._meta
        qn = self.connection.ops.quote_name

        table_output = [
            '    %s %s %s,' %
                (style.SQL_FIELD(qn(field.m2m_column_name())),
                style.SQL_COLTYPE(models.ForeignKey(model).db_type(connection=self.connection)),
                style.SQL_KEYWORD('NOT NULL')),
            '    %s %s %s,' %
            (style.SQL_FIELD(qn(field.m2m_reverse_name())),
            style.SQL_COLTYPE(models.ForeignKey(field.rel.to).db_type(connection=self.connection)),
            style.SQL_KEYWORD('NOT NULL'))
        ]
        deferred = [
            (field.m2m_qualified_table(), field.m2m_column_name(), opts.qualified_name,
                opts.pk.column),
            (field.m2m_qualified_table(), field.m2m_reverse_name(),
                field.rel.to._meta.qualified_name, field.rel.to._meta.pk.column)
            ]
        return table_output, deferred

    def sql_destroy_schema(self, schema, style):
        qn = self.connection.ops.quote_name
        return "%s %s;" % (style.SQL_KEYWORD('DROP DATABASE'), qn(schema))
    
    def qualified_index_name(self, model, col):
        """
        On MySQL we must use the db_schema prefixed to the index name as
        indexes can not be placed into different schemas.
        """
        from django.db.backends.util import truncate_name
        schema = model._meta.db_schema or self.connection.schema
        max_len = self.connection.ops.max_name_length()
        schema_prefix = ''
        if schema:
             schema = self.connection.convert_schema(schema)
             schema_prefix = truncate_name(schema, max_len / 2) + '_'
        i_name = '%s%s_%s' % (schema_prefix, model._meta.db_table, self._digest(col))
        i_name = self.connection.ops.quote_name(truncate_name(i_name, max_len))
        return i_name

    def qualified_name_for_ref(self, from_table, ref_table):
        """
        MySQL does not have qualified name format for indexes, so make sure to
        use qualified names if needed.
        """
        from_qn = self.connection.introspection.qname_converter(from_table)
        to_qn = self.connection.introspection.qname_converter(ref_table)
        if to_qn.schema is None:
            to_qn = QName(self.connection.settings_dict['NAME'],
                          to_qn.table, to_qn.db_format)
        return super(DatabaseCreation, self).qualified_name_for_ref(from_qn, to_qn)
