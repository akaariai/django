import sys
import time
from django.db import QName
from django.db.backends.creation import BaseDatabaseCreation
from django.core.management.color import no_style

TEST_DATABASE_PREFIX = 'test_'
PASSWORD = 'Im_a_lumberjack'

class DatabaseCreation(BaseDatabaseCreation):
    # This dictionary maps Field objects to their associated Oracle column
    # types, as strings. Column-type strings can contain format strings; they'll
    # be interpolated against the values of Field.__dict__ before being output.
    # If a column type is set to None, it won't be included in the output.
    #
    # Any format strings starting with "qn_" are quoted before being used in the
    # output (the "qn_" prefix is stripped before the lookup is performed.

    data_types = {
        'AutoField':                    'NUMBER(11)',
        'BooleanField':                 'NUMBER(1) CHECK (%(qn_column)s IN (0,1))',
        'CharField':                    'NVARCHAR2(%(max_length)s)',
        'CommaSeparatedIntegerField':   'VARCHAR2(%(max_length)s)',
        'DateField':                    'DATE',
        'DateTimeField':                'TIMESTAMP',
        'DecimalField':                 'NUMBER(%(max_digits)s, %(decimal_places)s)',
        'FileField':                    'NVARCHAR2(%(max_length)s)',
        'FilePathField':                'NVARCHAR2(%(max_length)s)',
        'FloatField':                   'DOUBLE PRECISION',
        'IntegerField':                 'NUMBER(11)',
        'BigIntegerField':              'NUMBER(19)',
        'IPAddressField':               'VARCHAR2(15)',
        'GenericIPAddressField':        'VARCHAR2(39)',
        'NullBooleanField':             'NUMBER(1) CHECK ((%(qn_column)s IN (0,1)) OR (%(qn_column)s IS NULL))',
        'OneToOneField':                'NUMBER(11)',
        'PositiveIntegerField':         'NUMBER(11) CHECK (%(qn_column)s >= 0)',
        'PositiveSmallIntegerField':    'NUMBER(11) CHECK (%(qn_column)s >= 0)',
        'SlugField':                    'NVARCHAR2(%(max_length)s)',
        'SmallIntegerField':            'NUMBER(11)',
        'TextField':                    'NCLOB',
        'TimeField':                    'TIMESTAMP',
        'URLField':                     'VARCHAR2(%(max_length)s)',
    }

    def __init__(self, connection):
        super(DatabaseCreation, self).__init__(connection)

    def _get_ddl_parameters(self):
        TEST_NAME = self._test_database_name()
        TEST_USER = self._test_database_user()
        TEST_PASSWD = self._test_database_passwd()
        TEST_TBLSPACE = self._test_database_tblspace()
        TEST_TBLSPACE_TMP = self._test_database_tblspace_tmp()
        return {
            'dbname': TEST_NAME,
            'user': TEST_USER,
            'password': TEST_PASSWD,
            'tblspace': TEST_TBLSPACE,
            'tblspace_temp': TEST_TBLSPACE_TMP,
        }

    def _create_test_db(self, verbosity=1, autoclobber=False, schemas=[]):
        parameters = self._get_ddl_parameters()
        cursor = self.connection.cursor()
        if self._test_database_create():
            try:
                self._execute_test_db_creation(cursor, parameters, verbosity)
            except Exception as e:
                sys.stderr.write("Got an error creating the test database: %s\n" % e)
                if not autoclobber:
                    confirm = raw_input("It appears the test database, %(dbname)s, already "
                                        "exists. Type 'yes' to delete it, or 'no' to cancel: "
                                        % parameters)
                if autoclobber or confirm == 'yes':
                    try:
                        if verbosity >= 1:
                            print("Destroying old test database '%s'..." % self.connection.alias)
                        self._execute_test_db_destruction(cursor, parameters, verbosity)
                        self._execute_test_db_creation(cursor, parameters, verbosity)
                    except Exception as e:
                        sys.stderr.write("Got an error recreating the test database: %s\n" % e)
                        sys.exit(2)
                else:
                    print("Tests cancelled.")
                    sys.exit(1)

        if self._test_user_create():
            if verbosity >= 1:
                print("Creating test user...")
            try:
                self._create_test_user(cursor, parameters, verbosity, dba=bool(schemas))
            except Exception as e:
                sys.stderr.write("Got an error creating the test user: %s\n" % e)
                if not autoclobber:
                    confirm = raw_input("It appears the test user, %(user)s, already exists. "
                                        "Type 'yes' to delete it, or 'no' to cancel: "
                                        % parameters)
                if autoclobber or confirm == 'yes':
                    try:
                        if verbosity >= 1:
                            print("Destroying old test user...")
                        self._destroy_test_user(cursor, parameters, verbosity)
                        if verbosity >= 1:
                            print("Creating test user...")
                        self._create_test_user(cursor, parameters, verbosity, dba=bool(schemas))
                    except Exception as e:
                        sys.stderr.write("Got an error recreating the test user: %s\n" % e)
                        sys.exit(2)
                else:
                    print("Tests cancelled.")
                    sys.exit(1)

        self.connection.settings_dict['SAVED_USER'] = self.connection.settings_dict['USER']
        self.connection.settings_dict['SAVED_PASSWORD'] = self.connection.settings_dict['PASSWORD']
        self.connection.settings_dict['TEST_USER'] = self.connection.settings_dict['USER'] = parameters['user']
        self.connection.settings_dict['PASSWORD'] = parameters['password']

        return self.connection.settings_dict['NAME']

    def _destroy_test_db(self, test_database_name, verbosity=1):
        """
        Destroy a test database, prompting the user for confirmation if the
        database already exists. Returns the name of the test database created.
        """
        parameters = self._get_ddl_parameters()
        self.connection.settings_dict['USER'] = self.connection.settings_dict['SAVED_USER']
        self.connection.settings_dict['PASSWORD'] = self.connection.settings_dict['SAVED_PASSWORD']

        cursor = self.connection.cursor()
        time.sleep(1) # To avoid "database is being accessed by other users" errors.
        if self._test_database_create():
            if verbosity >= 1:
                print('Destroying test database tables...')
            self._execute_test_db_destruction(cursor, parameters, verbosity)
        if self._test_user_create():
            if verbosity >= 1:
                print('Destroying test user...')
            self._destroy_test_user(cursor, parameters, verbosity)
        self.connection.close()

    def _execute_test_db_creation(self, cursor, parameters, verbosity):
        if verbosity >= 2:
            print("_create_test_db(): dbname = %s" % parameters['dbname'])
        statements = [
            """CREATE TABLESPACE %(tblspace)s
               DATAFILE '%(tblspace)s.dbf' SIZE 20M
               REUSE AUTOEXTEND ON NEXT 10M MAXSIZE 200M
            """,
            """CREATE TEMPORARY TABLESPACE %(tblspace_temp)s
               TEMPFILE '%(tblspace_temp)s.dbf' SIZE 20M
               REUSE AUTOEXTEND ON NEXT 10M MAXSIZE 100M
            """,
        ]
        self._execute_statements(cursor, statements, parameters, verbosity)

    def _create_test_user(self, cursor, parameters, verbosity, dba=False):
        parameters = parameters.copy()
        parameters['dba'] = ', DBA' if dba else ''
        if verbosity >= 2:
            print("_create_test_user(): username = %s" % parameters['user'])
        statements = [
            """CREATE USER %(user)s
               IDENTIFIED BY %(password)s
               DEFAULT TABLESPACE %(tblspace)s
               TEMPORARY TABLESPACE %(tblspace_temp)s
            """,
            """GRANT CONNECT, RESOURCE %(dba)s TO %(user)s""",
        ]
        self._execute_statements(cursor, statements, parameters, verbosity)

    def _execute_test_db_destruction(self, cursor, parameters, verbosity):
        if verbosity >= 2:
            print("_execute_test_db_destruction(): dbname=%s" % parameters['dbname'])
        statements = [
            'DROP TABLESPACE %(tblspace)s INCLUDING CONTENTS AND DATAFILES CASCADE CONSTRAINTS',
            'DROP TABLESPACE %(tblspace_temp)s INCLUDING CONTENTS AND DATAFILES CASCADE CONSTRAINTS',
            ]
        self._execute_statements(cursor, statements, parameters, verbosity)

    def _destroy_test_user(self, cursor, parameters, verbosity):
        if verbosity >= 2:
            print("_destroy_test_user(): user=%s" % parameters['user'])
            print("Be patient.  This can take some time...")
        statements = [
            self.sql_destroy_schema(parameters['user'], style=None)
        ]
        self._execute_statements(cursor, statements, parameters, verbosity)

    def sql_destroy_schema(self, schema, style):
        return "DROP USER %s CASCADE" % schema

    def _execute_statements(self, cursor, statements, parameters, verbosity):
        for template in statements:
            stmt = template % parameters
            if verbosity >= 2:
                print(stmt)
            try:
                cursor.execute(stmt)
            except Exception as err:
                sys.stderr.write("Failed (%s)\n" % (err))
                raise

    def _test_database_name(self):
        name = TEST_DATABASE_PREFIX + self.connection.settings_dict['NAME']
        try:
            if self.connection.settings_dict['TEST_NAME']:
                name = self.connection.settings_dict['TEST_NAME']
        except AttributeError:
            pass
        return name

    def _test_database_create(self):
        return self.connection.settings_dict.get('TEST_CREATE', True)

    def _test_user_create(self):
        return self.connection.settings_dict.get('TEST_USER_CREATE', True)

    def _test_database_user(self):
        name = TEST_DATABASE_PREFIX + self.connection.settings_dict['USER']
        try:
            if self.connection.settings_dict['TEST_USER']:
                name = self.connection.settings_dict['TEST_USER']
        except KeyError:
            pass
        return name

    def _test_database_passwd(self):
        name = PASSWORD
        try:
            if self.connection.settings_dict['TEST_PASSWD']:
                name = self.connection.settings_dict['TEST_PASSWD']
        except KeyError:
            pass
        return name

    def _test_database_tblspace(self):
        name = TEST_DATABASE_PREFIX + self.connection.settings_dict['NAME']
        try:
            if self.connection.settings_dict['TEST_TBLSPACE']:
                name = self.connection.settings_dict['TEST_TBLSPACE']
        except KeyError:
            pass
        return name

    def _test_database_tblspace_tmp(self):
        name = TEST_DATABASE_PREFIX + self.connection.settings_dict['NAME'] + '_temp'
        try:
            if self.connection.settings_dict['TEST_TBLSPACE_TMP']:
                name = self.connection.settings_dict['TEST_TBLSPACE_TMP']
        except KeyError:
            pass
        return name

    def _get_test_db_name(self):
        """
        We need to return the 'production' DB name to get the test DB creation
        machinery to work. This isn't a great deal in this case because DB
        names as handled by Django haven't real counterparts in Oracle.
        """
        return self.connection.settings_dict['NAME']

    def test_db_signature(self):
        settings_dict = self.connection.settings_dict
        return (
            settings_dict['HOST'],
            settings_dict['PORT'],
            settings_dict['ENGINE'],
            settings_dict['NAME'],
            self._test_database_user(),
        )

    def set_autocommit(self):
        self.connection.connection.autocommit = True

    def _create_test_schemas(self, verbosity, schemas, autoclobber):
        if not self._test_user_create():
            return []
        cursor = self.connection.cursor()
        parameters = self._get_ddl_parameters()
        parameters['authorization'] = parameters['user']
        conv = self.connection.introspection.identifier_converter
        existing_schemas = [conv(s) for s in self.connection.introspection.get_schema_list(cursor)]
        conflicts = [conv(s) for s in existing_schemas if conv(s) in schemas]
        if conflicts:
            print 'The following users already exists: %s' % ', '.join(conflicts) 
            if not autoclobber:
                confirm = raw_input(
                    "Type 'yes' if you would like to try deleting these users "
                    "or 'no' to cancel: ")
            if autoclobber or confirm == 'yes':
                for schema in conflicts:
                    parameters['user'] = schema
                    if verbosity >= 1:
                        print "Destroying user %s" % schema
                    self._destroy_test_user(cursor, parameters, verbosity)
                    existing_schemas.remove(schema)
            else:
                print "Tests cancelled."
                sys.exit(1)
           
        to_create = [s for s in schemas if s not in existing_schemas]
        for schema in to_create:
            parameters['user'] = schema
            if verbosity >= 1:
                print "Creating user %s" % schema
            self._create_test_user(cursor, parameters, verbosity)
        return to_create

    def needs_separate_conn(self, from_qname, to_qname):
        conv = self.connection.introspection.qname_converter
        def_schema = conv(QName(None, None, False), force_schema=True).schema
        from_qname = conv(from_qname, force_schema=True)
        to_qname = conv(to_qname, force_schema=True)
        return (def_schema != from_qname.schema
                or to_qname.schema != from_qname.schema)

    def sql_for_inline_foreign_key_references(self, field, known_models, style):
        """
        Return the SQL snippet defining the foreign key reference for a field.

        Oracle doesn't let you do cross-schema foreign keys, except if you
        are connected to the "from" schema. Don't ask why.
        """
        if self.needs_separate_conn(field.model._meta.qualified_name,
                                    field.rel.to._meta.qualified_name):
            return [], True
        return super(DatabaseCreation, self).sql_for_inline_foreign_key_references(field, known_models, style)

    def sql_for_pending_references(self, model, style, pending_references,
                                   second_pass=False):
        """
        Sad fact of life: On Oracle it is impossible to do cross-schema
        references unless you explisitly grant REFERENCES on the referenced
        table, and in addition the reference is made from the schema
        containing the altered table (the one getting the new constraint).
        To make this even nicer, it is impossible to do the GRANT using the
        same user we are giving the REFERENCES right, as you can't GRANT
        yourself.

        The solution we are using is to do the pending cross-schema references
        in two stages after all tables have been created:
            1) Connect as the foreign key's target table owner, and grant
               REFERENCES to all users needing to do foreign keys.
            2) Connect as the source table's owner, and create the foreign
               keys.
        To support this arrangement, we will create only non-cross-schema
        references unless we are explicitly told by the second_pass flag
        that it is safe to do the cross schema references.

        It is possible to grant REFERENCES to public (but it seems other roles
        will not work), but as we need to anyways do this multi-connection
        dance it seems better to do the grants explicitly only when needed.
        """
        if second_pass:
            return super(DatabaseCreation, self).sql_for_pending_references(
                model, style, pending_references)
        # Split the "safe" and "unsafe" references apart, and call
        # the super() method for the safe set.
        cross_schema_refs = []
        single_schema_refs = []
        if model in pending_references:
            for rel_class, f in pending_references[model]:
                if self.needs_separate_conn(rel_class._meta.qualified_name,
                                            model._meta.qualified_name):
                    cross_schema_refs.append((rel_class, f))
                else:
                    single_schema_refs.append((rel_class, f))
        sql = []
        if single_schema_refs:
            pending_references[model] = single_schema_refs
            sql = super(DatabaseCreation, self).sql_for_pending_references(
                model, style, pending_references)
        if cross_schema_refs:
            pending_references[model] = cross_schema_refs
        return sql

    def post_create_pending_references(self, pending_references, as_sql=False):
        # Build a dictionary: from_schema -> [(model, refs)...]
        references_to_schema = {}
        sql = []
        conv = self.connection.introspection.qname_converter
        for model, refs in pending_references.items():
            schema = conv(model._meta.qualified_name, force_schema=True).schema
            if schema not in references_to_schema:
                references_to_schema[schema] = []
            references_to_schema[schema].append((model, refs))
        # Pass 1: give grants.
        for schema, all_refs in references_to_schema.items():
            grant_to = set()
            for model, refs in all_refs:
                for ref in refs:
                    to_user = conv(ref[0]._meta.qualified_name,
                                   force_schema=True).schema
                    if to_user != schema:
                        grant_to.add((model, to_user))
            sql.extend(self._grant_references(schema, grant_to, as_sql))
        # Prepare for pass 2. This time we must connect as the user
        # of the altered table's schema. So, first build a dictionary of
        # from_schema -> [{model: [refs]}], that is, build a
        # pending_references for each schema separately.
        references_from_schema = {}
        for model, refs in pending_references.items():
            for ref in refs:
                schema = conv(ref[0]._meta.qualified_name,
                              force_schema=True).schema
                if schema not in references_from_schema:
                    references_from_schema[schema] = {}
                if model not in references_from_schema[schema]:
                    references_from_schema[schema][model] = []
                references_from_schema[schema][model].append(ref)
        # Pass 2: create the actual references
        for schema, ref_dict in references_from_schema.items():
            per_schema_sql = ['-- Connect as user "%s"' % schema] if as_sql else []
            for model, refs in ref_dict.items():
                ref_sql = self.sql_for_pending_references(model, no_style(),
                                                          ref_dict, second_pass=True)
                per_schema_sql.extend(ref_sql)
            if not as_sql:
                self._run_sql_as_user(schema, per_schema_sql)
            sql.extend(per_schema_sql)
        return sql

    def _grant_references(self, schema, grant_to, as_sql):
        sql = ['-- Connect as user "%s"' % schema] if as_sql else []
        qn = self.connection.ops.quote_name
        for model, user in grant_to:
            sql.append('GRANT REFERENCES ON %s TO %s'
                       % (qn(model._meta.db_table), qn(user)))
        if not as_sql:
            self._run_sql_as_user(schema, sql)
        return sql

    def _run_sql_as_user(self, user, sql):
        if not sql:
            return
        self.connection.close()
        try:
            old_settings = self.connection.settings_dict.copy()
            self.connection.settings_dict['USER'] = user
            cursor = self.connection.cursor()
            for q in sql:
                cursor.execute(q)
        finally:
            self.connection.close()
            self.connection.settings_dict = old_settings
