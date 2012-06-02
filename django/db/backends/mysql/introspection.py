from django.db import QName
from django.db.backends import BaseDatabaseIntrospection
from MySQLdb import ProgrammingError, OperationalError
from MySQLdb.constants import FIELD_TYPE
import re

foreign_key_re = re.compile(r"\sCONSTRAINT `[^`]*` FOREIGN KEY \(`([^`]*)`\) REFERENCES `([^`]*)` \(`([^`]*)`\)")

class DatabaseIntrospection(BaseDatabaseIntrospection):
    data_types_reverse = {
        FIELD_TYPE.BLOB: 'TextField',
        FIELD_TYPE.CHAR: 'CharField',
        FIELD_TYPE.DECIMAL: 'DecimalField',
        FIELD_TYPE.NEWDECIMAL: 'DecimalField',
        FIELD_TYPE.DATE: 'DateField',
        FIELD_TYPE.DATETIME: 'DateTimeField',
        FIELD_TYPE.DOUBLE: 'FloatField',
        FIELD_TYPE.FLOAT: 'FloatField',
        FIELD_TYPE.INT24: 'IntegerField',
        FIELD_TYPE.LONG: 'IntegerField',
        FIELD_TYPE.LONGLONG: 'BigIntegerField',
        FIELD_TYPE.SHORT: 'IntegerField',
        FIELD_TYPE.STRING: 'CharField',
        FIELD_TYPE.TIMESTAMP: 'DateTimeField',
        FIELD_TYPE.TINY: 'IntegerField',
        FIELD_TYPE.TINY_BLOB: 'TextField',
        FIELD_TYPE.MEDIUM_BLOB: 'TextField',
        FIELD_TYPE.LONG_BLOB: 'TextField',
        FIELD_TYPE.VAR_STRING: 'CharField',
    }

    def get_visible_tables_list(self, cursor):
        "Returns a list of visible tables"
        return self.get_qualified_tables_list(cursor, [self.connection.settings_dict['NAME']])

    def get_qualified_tables_list(self, cursor, schemas):
        default_schema = self.connection.convert_schema(None)
        if default_schema:
            schemas.append(default_schema)
        if not schemas:
            return []
        param_list = ', '.join(['%s']*len(schemas))
        cursor.execute("""
            SELECT table_schema, table_name
              FROM information_schema.tables
             WHERE table_schema in (%s)""" % param_list, schemas)
        return [QName(row[0], row[1], True) for row in cursor.fetchall()]

    def get_table_description(self, cursor, qname):
        "Returns a description of the table, with the DB-API cursor.description interface."
        qname = self.qname_converter(qname)
        cursor.execute("SELECT * FROM %s LIMIT 1"
                       % self.connection.ops.qualified_name(qname))
        return cursor.description

    def _name_to_index(self, cursor, qname):
        """
        Returns a dictionary of {field_name: field_index} for the given table.
        Indexes are 0-based.
        """
        return dict((d[0], i) for i, d in enumerate(self.get_table_description(cursor, qname)))

    def get_relations(self, cursor, qname):
        """
        Returns a dictionary of {field_index: (field_index_other_table, other_table)}
        representing all relationships to the given table. Indexes are 0-based.
        """
        my_field_dict = self._name_to_index(cursor, qname)
        constraints = self.get_key_columns(cursor, qname)
        relations = {}
        for my_fieldname, other_table, other_field in constraints:
            other_field_index = self._name_to_index(cursor, other_table)[other_field]
            my_field_index = my_field_dict[my_fieldname]
            relations[my_field_index] = (other_field_index, other_table)
        return relations

    def get_key_columns(self, cursor, qname):
        """
        Returns a list of (column_name, referenced_table_name, referenced_column_name) for all
        key columns in given table.
        """
        key_columns = []
        qname = self.qname_converter(qname, force_schema=True)
        cursor.execute("""
            SELECT column_name, referenced_table_schema, referenced_table_name,
                   referenced_column_name
            FROM information_schema.key_column_usage
            WHERE table_name = %s
                AND table_schema = %s
                AND referenced_table_name IS NOT NULL
                AND referenced_column_name IS NOT NULL""", [qname.table, qname.schema])
        for row in cursor.fetchall():
            key_columns.append((row[0], QName(row[1], row[2], True),
                                row[3]))
        return key_columns

    def get_primary_key_column(self, cursor, qname):
        """
        Returns the name of the primary key column for the given table
        """
        for column in self.get_indexes(cursor, qname).iteritems():
            if column[1]['primary_key']:
                return column[0]
        return None

    def get_indexes(self, cursor, qname):
        """
        Returns a dictionary of fieldname -> infodict for the given table,
        where each infodict is in the format:
            {'primary_key': boolean representing whether it's the primary key,
             'unique': boolean representing whether it's a unique index}
        """
        qname = self.qname_converter(qname)
        cursor.execute("SHOW INDEX FROM %s" % self.connection.ops.qualified_name(qname))
        # Do a two-pass search for indexes: on first pass check which indexes
        # are multicolumn, on second pass check which single-column indexes
        # are present.
        rows = list(cursor.fetchall())
        multicol_indexes = set()
        for row in rows:
            if row[3] > 1:
                multicol_indexes.add(row[2])
        indexes = {}
        for row in rows:
            if row[2] in multicol_indexes:
                continue
            indexes[row[4]] = {'primary_key': (row[2] == 'PRIMARY'), 'unique': not bool(row[1])}
        return indexes

    def get_schema_list(self, cursor):
        cursor.execute("SHOW DATABASES")
        return [r[0] for r in cursor.fetchall()]

    def qname_converter(self, qname, force_schema=False):
        assert isinstance(qname, QName)
        if qname.db_format and (qname.schema or not force_schema):
            return qname
        schema = self.connection.convert_schema(qname.schema)
        if not schema and force_schema:
            schema = self.connection.settings_dict['NAME']
        return QName(schema, qname.table, True)
