import sys
import time

from django.conf import settings
from django.db import QName
from django.db.utils import load_backend
from django.core.management.color import no_style

# The prefix to put on the default database name when creating
# the test database.
TEST_DATABASE_PREFIX = 'test_'


class BaseDatabaseCreation(object):
    """
    This class encapsulates all backend-specific differences that pertain to
    database *creation*, such as the column types to use for particular Django
    Fields, the SQL used to create and destroy tables, and the creation and
    destruction of test databases.
    """
    data_types = {}

    def __init__(self, connection):
        self.connection = connection

    def _digest(self, *args):
        """
        Generates a 32-bit digest of a set of arguments that can be used to
        shorten identifying names.
        """
        return '%x' % (abs(hash(args)) % 4294967296L)  # 2**32

    def sql_create_schema(self, schema, style):
        """
        Returns the SQL required to create a single schema
        """
        qn = self.connection.ops.quote_name
        output = "%s %s;" % (style.SQL_KEYWORD('CREATE SCHEMA'), qn(schema))
        return output

    def sql_create_model(self, model, style, known_models=set()):
        """
        Returns the SQL required to create a single model, as a tuple of:
            (list_of_sql, pending_references_dict)
        """
        opts = model._meta
        if not opts.managed or opts.proxy:
            return [], {}
        final_output = []
        table_output = []
        pending_references = {}
        qn = self.connection.ops.quote_name
        qn3 = self.connection.ops.qualified_name
        for f in opts.local_fields:
            col_type = f.db_type(connection=self.connection)
            tablespace = f.db_tablespace or opts.db_tablespace
            if col_type is None:
                # Skip ManyToManyFields, because they're not represented as
                # database columns in this table.
                continue
            # Make the definition (e.g. 'foo VARCHAR(30)') for this field.
            field_output = [style.SQL_FIELD(qn(f.column)),
                style.SQL_COLTYPE(col_type)]
            # Oracle treats the empty string ('') as null, so coerce the null
            # option whenever '' is a possible value.
            null = f.null
            if (f.empty_strings_allowed and not f.primary_key and
                    self.connection.features.interprets_empty_strings_as_nulls):
                null = True
            if not null:
                field_output.append(style.SQL_KEYWORD('NOT NULL'))
            if f.primary_key:
                field_output.append(style.SQL_KEYWORD('PRIMARY KEY'))
            elif f.unique:
                field_output.append(style.SQL_KEYWORD('UNIQUE'))
            if tablespace and f.unique:
                # We must specify the index tablespace inline, because we
                # won't be generating a CREATE INDEX statement for this field.
                tablespace_sql = self.connection.ops.tablespace_sql(
                    tablespace, inline=True)
                if tablespace_sql:
                    field_output.append(tablespace_sql)
            if f.rel:
                ref_output, pending = self.sql_for_inline_foreign_key_references(
                    f, known_models, style)
                if pending:
                    pending_references.setdefault(f.rel.to, []).append(
                        (model, f))
                else:
                    field_output.extend(ref_output)
            table_output.append(' '.join(field_output))
        for field_constraints in opts.unique_together:
            table_output.append(style.SQL_KEYWORD('UNIQUE') + ' (%s)' %
                ", ".join(
                    [style.SQL_FIELD(qn(opts.get_field(f).column))
                     for f in field_constraints]))

        full_statement = [style.SQL_KEYWORD('CREATE TABLE') + ' ' +
                          style.SQL_TABLE(qn3(opts.qualified_name)) + ' (']
        for i, line in enumerate(table_output): # Combine and add commas.
            full_statement.append(
                '    %s%s' % (line, i < len(table_output)-1 and ',' or ''))
        full_statement.append(')')
        if opts.db_tablespace:
            tablespace_sql = self.connection.ops.tablespace_sql(
                opts.db_tablespace)
            if tablespace_sql:
                full_statement.append(tablespace_sql)
        full_statement.append(';')
        final_output.append('\n'.join(full_statement))

        if opts.has_auto_field:
            # Add any extra SQL needed to support auto-incrementing primary
            # keys.
            auto_column = opts.auto_field.db_column or opts.auto_field.name
            autoinc_sql = self.connection.ops.autoinc_sql(opts.qualified_name,
                                                          auto_column)
            if autoinc_sql:
                for stmt in autoinc_sql:
                    final_output.append(stmt)

        return final_output, pending_references

    def sql_for_inline_foreign_key_references(self, field, known_models, style):
        """
        Return the SQL snippet defining the foreign key reference for a field.
        """
        qn = self.connection.ops.quote_name
        from_qname = field.model._meta.qualified_name
        to_qname = field.rel.to._meta.qualified_name
        qname = self.qualified_name_for_ref(from_qname, to_qname)
        if field.rel.to in known_models:
            output = [style.SQL_KEYWORD('REFERENCES') + ' ' +
                style.SQL_TABLE(qname) + ' (' +
                style.SQL_FIELD(qn(field.rel.to._meta.get_field(
                    field.rel.field_name).column)) + ')' +
                self.connection.ops.deferrable_sql()
            ]
            pending = False
        else:
            # We haven't yet created the table to which this field
            # is related, so save it for later.
            output = []
            pending = True

        return output, pending

    def sql_for_pending_references(self, model, style, pending_references):
        """
        Returns any ALTER TABLE statements to add constraints after the fact.
        """
        from django.db.backends.util import truncate_name

        if not model._meta.managed or model._meta.proxy:
            # So, we have a reference to either unmanaged model or to
            # a proxy model. Lets just clear the pending_references
            # for now.
            if model in pending_references:
                del pending_references[model]
            return []
        qn = self.connection.ops.quote_name
        qn3 = self.connection.ops.qualified_name
        final_output = []
        opts = model._meta
        if model in pending_references:
            for rel_class, f in pending_references[model]:
                rel_opts = rel_class._meta
                r_table = rel_opts.db_table
                r_qname = rel_opts.qualified_name
                r_col = f.column
                table = opts.db_table
                qname = self.qualified_name_for_ref(r_qname, opts.qualified_name)
                col = opts.get_field(f.rel.field_name).column
                # For MySQL, r_name must be unique in the first 64 characters.
                # So we are careful with character usage here.
                r_name = '%s_refs_%s_%s' % (
                    r_col, col, self._digest(r_table, table))
                final_output.append(style.SQL_KEYWORD('ALTER TABLE') +
                    ' %s ADD CONSTRAINT %s FOREIGN KEY (%s) REFERENCES %s (%s)%s;' %
                    (qn3(r_qname), qn(truncate_name(
                        r_name, self.connection.ops.max_name_length())),
                    qn(r_col), qname, qn(col),
                    self.connection.ops.deferrable_sql()))
            del pending_references[model]
        return final_output

    def qualified_name_for_ref(self, from_table, ref_table):
        """
        In certain databases if the from_table is in qualified format and
        ref_table is not, it is assumed the ref_table references a table
        in the same schema as from_table is from. However, we want the
        reference to be to default schema, not the same schema the from_table
        is. This method will fix this issue where that is a problem.
        """
        return self.connection.ops.qualified_name(ref_table)

    def sql_indexes_for_model(self, model, style):
        """
        Returns the CREATE INDEX SQL statements for a single model.
        """
        if not model._meta.managed or model._meta.proxy:
            return []
        output = []
        for f in model._meta.local_fields:
            output.extend(self.sql_indexes_for_field(model, f, style))
        return output

    def sql_indexes_for_field(self, model, f, style):
        """
        Return the CREATE INDEX SQL statements for a single model field.
        """
        if f.db_index and not f.unique:
            qn = self.connection.ops.quote_name
            qn3 = self.connection.ops.qualified_name
            tablespace = f.db_tablespace or model._meta.db_tablespace
            if tablespace:
                tablespace_sql = self.connection.ops.tablespace_sql(tablespace)
                if tablespace_sql:
                    tablespace_sql = ' ' + tablespace_sql
            else:
                tablespace_sql = ''
            qualified_name = self.qualified_index_name(model, f.column) 
            output = [style.SQL_KEYWORD('CREATE INDEX') + ' ' +
                style.SQL_TABLE(qualified_name) + ' ' +
                style.SQL_KEYWORD('ON') + ' ' +
                style.SQL_TABLE(qn3(model._meta.qualified_name)) + ' ' +
                "(%s)" % style.SQL_FIELD(qn(f.column)) +
                "%s;" % tablespace_sql]
        else:
            output = []
        return output

    def qualified_index_name(self, model, col):
        """
        Some databases do support schemas, but indexes can not be placed in a
        different schema. So, to support those databases, we need to be able
        to return the index name in different qualified format than the rest
        of the database identifiers.
        """
        from django.db.backends.util import truncate_name
        i_name = '%s_%s' % (model._meta.db_table, self._digest(col))
        i_name = truncate_name(i_name, self.connection.ops.max_name_length())
        return self.connection.ops.qualified_name(
            QName(model._meta.db_schema, i_name, False))

    def sql_destroy_schema(self, schema, style):
        """
        Returns the SQL required to destroy a single schema.
        """
        return ""

    def sql_destroy_model(self, model, references_to_delete, style):
        """
        Return the DROP TABLE and restraint dropping statements for a single
        model.
        """
        if not model._meta.managed or model._meta.proxy:
            return []
        # Drop the table now
        qn3 = self.connection.ops.qualified_name
        output = ['%s %s;' % (style.SQL_KEYWORD('DROP TABLE'),
                              style.SQL_TABLE(qn3(model._meta.qualified_name)))]
        if model in references_to_delete:
            output.extend(self.sql_remove_table_constraints(
                model, references_to_delete, style))
        if model._meta.has_auto_field:
            ds = self.connection.ops.drop_sequence_sql(model._meta.qualified_name)
            if ds:
                output.append(ds)
        return output

    def sql_remove_table_constraints(self, model, references_to_delete, style):
        from django.db.backends.util import truncate_name
        if not model._meta.managed or model._meta.proxy:
            return []
        output = []
        qn = self.connection.ops.quote_name
        qn3 = self.connection.ops.qualified_name
        for rel_class, f in references_to_delete[model]:
            table = rel_class._meta.db_table
            qname = rel_class._meta.qualified_name
            col = f.column
            r_table = model._meta.db_table
            r_col = model._meta.get_field(f.rel.field_name).column
            r_name = '%s_refs_%s_%s' % (
                col, r_col, self._digest(table, r_table))
            output.append('%s %s %s %s;' % \
                (style.SQL_KEYWORD('ALTER TABLE'),
                style.SQL_TABLE(qn3(qname)),
                style.SQL_KEYWORD(self.connection.ops.drop_foreignkey_sql()),
                style.SQL_FIELD(qn(truncate_name(
                    r_name, self.connection.ops.max_name_length())))))
        del references_to_delete[model]
        return output

    def create_test_db(self, verbosity=1, autoclobber=False):
        """
        Creates a test database, prompting the user for confirmation if the
        database already exists. Returns the name of the test database created.

        Also creates needed schemas, which on some backends live in the same
        namespace than databases. If there are schema name clashes, prompts
        the user for confirmation.
        """
        # Don't import django.core.management if it isn't needed.
        from django.core.management import call_command

        test_database_name = self._get_test_db_name()

        if verbosity >= 1:
            test_db_repr = ''
            if verbosity >= 2:
                test_db_repr = " ('%s')" % test_database_name
            print("Creating test database for alias '%s'%s..." % (
                self.connection.alias, test_db_repr))

        schemas = self.get_schemas()
        self._create_test_db(verbosity, autoclobber, schemas)

        self.connection.close()
        self.connection.settings_dict["NAME"] = test_database_name

        # Create the test schemas.
        schemas = ['%s%s' % (self.connection.test_schema_prefix, s) for s in schemas]
        created_schemas = self._create_test_schemas(verbosity, schemas, autoclobber)

        # Confirm the feature set of the test database
        self.connection.features.confirm()

        # Report syncdb messages at one level lower than that requested.
        # This ensures we don't get flooded with messages during testing
        # (unless you really ask to be flooded)
        call_command('syncdb',
            verbosity=max(verbosity - 1, 0),
            interactive=False,
            database=self.connection.alias,
            load_initial_data=False)

        # We need to then do a flush to ensure that any data installed by
        # custom SQL has been removed. The only test data should come from
        # test fixtures, or autogenerated from post_syncdb triggers.
        # This has the side effect of loading initial data (which was
        # intentionally skipped in the syncdb).
        call_command('flush',
            verbosity=max(verbosity - 1, 0),
            interactive=False,
            database=self.connection.alias)

        from django.core.cache import get_cache
        from django.core.cache.backends.db import BaseDatabaseCache
        for cache_alias in settings.CACHES:
            cache = get_cache(cache_alias)
            if isinstance(cache, BaseDatabaseCache):
                call_command('createcachetable', cache._table,
                             database=self.connection.alias)

        # Get a cursor (even though we don't need one yet). This has
        # the side effect of initializing the test database.
        self.connection.cursor()

        return test_database_name, created_schemas

    def _create_test_schemas(self, verbosity, schemas, autoclobber):
        style = no_style()
        cursor = self.connection.cursor()
        existing_schemas = self.connection.introspection.get_schema_list(cursor)
        if not self.connection.features.namespaced_schemas:
            conflicts = [s for s in existing_schemas if s in schemas]
        else:
            conflicts = []
        if conflicts:
            print 'The following schemas already exists: %s' % ', '.join(conflicts) 
            if not autoclobber:
                confirm = raw_input(
                    "Type 'yes' if you would like to try deleting these schemas "
                    "or 'no' to cancel: ")
            if autoclobber or confirm == 'yes':
                try:
                    # Some databases (well, MySQL) complain about foreign keys when
                    # dropping a database. So, disable the constraints temporarily.
                    self.connection.disable_constraint_checking()
                    for schema in conflicts:
                        if verbosity >= 1:
                            print "Destroying schema %s" % schema
                        cursor.execute(self.sql_destroy_schema(schema, style))
                        existing_schemas.remove(schema)
                finally:
                    self.connection.enable_constraint_checking()
            else:
                print "Tests cancelled."
                sys.exit(1)
           
        to_create = [s for s in schemas if s not in existing_schemas]
        for schema in to_create:
            if verbosity >= 1:
                print "Creating schema %s" % schema
            cursor.execute(self.sql_create_schema(schema, style))
            self.connection.settings_dict['TEST_SCHEMAS'].append(schema)
        return to_create

    def get_schemas(self):
        from django.db import models
        apps = models.get_apps()
        schemas = set()
        for app in apps:
            app_models = models.get_models(app, include_auto_created=True)
            for model in app_models:
                schema = model._meta.db_schema
                if schema:
                    schemas.add(schema)
        conn_default_schema = self.connection.settings_dict['SCHEMA']
        if conn_default_schema:
            schemas.add(conn_default_schema)
        return schemas

    def _get_test_db_name(self):
        """
        Internal implementation - returns the name of the test DB that will be
        created. Only useful when called from create_test_db() and
        _create_test_db() and when no external munging is done with the 'NAME'
        or 'TEST_NAME' settings.
        """
        if self.connection.settings_dict['TEST_NAME']:
            return self.connection.settings_dict['TEST_NAME']
        return TEST_DATABASE_PREFIX + self.connection.settings_dict['NAME']

    def _create_test_db(self, verbosity, autoclobber, schemas):
        """
        Internal implementation - creates the test db tables.
        """
        suffix = self.sql_table_creation_suffix()

        test_database_name = self._get_test_db_name()

        qn = self.connection.ops.quote_name

        # Create the test database and connect to it. We need to autocommit
        # if the database supports it because PostgreSQL doesn't allow
        # CREATE/DROP DATABASE statements within transactions.
        cursor = self.connection.cursor()
        self._prepare_for_test_db_ddl()
        try:
            cursor.execute(
                "CREATE DATABASE %s %s" % (qn(test_database_name), suffix))
        except Exception as e:
            sys.stderr.write(
                "Got an error creating the test database: %s\n" % e)
            if not autoclobber:
                confirm = raw_input(
                    "Type 'yes' if you would like to try deleting the test "
                    "database '%s', or 'no' to cancel: " % test_database_name)
            if autoclobber or confirm == 'yes':
                try:
                    if verbosity >= 1:
                        print("Destroying old test database '%s'..."
                              % self.connection.alias)
                    # MySQL doesn't have a drop-cascade option, nor does it
                    # allow dropping a database having foreign key references
                    # pointing to it. So, we just disable foreign key checks
                    # and then immediately enable them. MySQL is happy after
                    # this hack, and other databases simply do not care.
                    try:
                        self.connection.disable_constraint_checking()
                        cursor.execute(
                            "DROP DATABASE %s" % qn(test_database_name))
                    finally:
                        self.connection.enable_constraint_checking()
                    cursor.execute(
                        "CREATE DATABASE %s %s" % (qn(test_database_name),
                                                   suffix))
                except Exception as e:
                    sys.stderr.write(
                        "Got an error recreating the test database: %s\n" % e)
                    sys.exit(2)
            else:
                print("Tests cancelled.")
                sys.exit(1)

        self.connection.settings_dict['TEST_SCHEMAS'].append(test_database_name)
        return test_database_name

    def destroy_test_db(self, old_database_name, created_schemas, verbosity=1):
        """
        Destroy a test database, prompting the user for confirmation if the
        database already exists.
        """
        # On databases where the schemas are not dropped when the database
        # is dropped we need to destroy the created schemas manually.
        cursor = self.connection.cursor()
        style = no_style()
        if not self.connection.features.namespaced_schemas:
            try:
                self.connection.disable_constraint_checking()
                for schema in created_schemas:
                    if verbosity >= 1:
                        print "Destroying schema '%s'..." % schema
                    cursor.execute(self.sql_destroy_schema(schema, style))
            finally:
                self.connection.enable_constraint_checking()
        self.connection.close()
        test_database_name = self.connection.settings_dict['NAME']
        if verbosity >= 1:
            test_db_repr = ''
            if verbosity >= 2:
                test_db_repr = " ('%s')" % test_database_name
            print("Destroying test database for alias '%s'%s..." % (
                self.connection.alias, test_db_repr))

        # Temporarily use a new connection and a copy of the settings dict.
        # This prevents the production database from being exposed to potential
        # child threads while (or after) the test database is destroyed.
        # Refs #10868 and #17786.
        settings_dict = self.connection.settings_dict.copy()
        settings_dict['NAME'] = old_database_name
        backend = load_backend(settings_dict['ENGINE'])
        new_connection = backend.DatabaseWrapper(
                             settings_dict,
                             alias='__destroy_test_db__',
                             allow_thread_sharing=False)
        new_connection.creation._destroy_test_db(test_database_name, verbosity)

    def _destroy_test_db(self, test_database_name, verbosity):
        """
        Internal implementation - remove the test db tables.
        """
        # Remove the test database to clean up after
        # ourselves. Connect to the previous database (not the test database)
        # to do so, because it's not allowed to delete a database while being
        # connected to it.
        cursor = self.connection.cursor()
        self._prepare_for_test_db_ddl()
        # Wait to avoid "database is being accessed by other users" errors.
        time.sleep(1)
        try:
            self.connection.disable_constraint_checking()
            cursor.execute("DROP DATABASE %s"
                           % self.connection.ops.quote_name(test_database_name))
        finally:
            self.connection.enable_constraint_checking()
        self.connection.close()

    def set_autocommit(self):
        """
        Make sure a connection is in autocommit mode. - Deprecated, not used
        anymore by Django code. Kept for compatibility with user code that
        might use it.
        """
        pass

    def _prepare_for_test_db_ddl(self):
        """
        Internal implementation - Hook for tasks that should be performed
        before the ``CREATE DATABASE``/``DROP DATABASE`` clauses used by
        testing code to create/ destroy test databases. Needed e.g. in
        PostgreSQL to rollback and close any active transaction.
        """
        pass

    def sql_table_creation_suffix(self):
        """
        SQL to append to the end of the test table creation statements.
        """
        return ''

    def test_db_signature(self):
        """
        Returns a tuple with elements of self.connection.settings_dict (a
        DATABASES setting value) that uniquely identify a database
        accordingly to the RDBMS particularities.
        """
        settings_dict = self.connection.settings_dict
        return (
            settings_dict['HOST'],
            settings_dict['PORT'],
            settings_dict['ENGINE'],
            settings_dict['NAME']
        )

    def post_create_pending_references(self, pending_references, as_sql=False):
        """
        Create any pending references which need special handling (for example
        different connections). The as_sql flag tells us if we should return
        the raw SQL used. This is needed for the "sql" management commands.
        """
        raise NotImplementedError
