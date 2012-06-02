from optparse import make_option
import traceback

from django.conf import settings
from django.core.management.base import NoArgsCommand
from django.core.management.color import no_style
from django.core.management.sql import custom_sql_for_model, emit_post_sync_signal
from django.db import connections, router, transaction, models, DEFAULT_DB_ALIAS
from django.utils.datastructures import SortedDict
from django.utils.importlib import import_module


class Command(NoArgsCommand):
    option_list = NoArgsCommand.option_list + (
        make_option('--noinput', action='store_false', dest='interactive', default=True,
            help='Tells Django to NOT prompt the user for input of any kind.'),
        make_option('--database', action='store', dest='database',
            default=DEFAULT_DB_ALIAS, help='Nominates a database to synchronize. '
                'Defaults to the "default" database.'),
    )
    help = "Create the database tables for all apps in INSTALLED_APPS whose tables haven't already been created."

    def handle_noargs(self, **options):

        verbosity = int(options.get('verbosity'))
        interactive = options.get('interactive')
        show_traceback = options.get('traceback')

        # Stealth option -- 'load_initial_data' is used by the testing setup
        # process to disable initial fixture loading.
        load_initial_data = options.get('load_initial_data', True)

        self.style = no_style()

        # Import the 'management' module within each installed app, to register
        # dispatcher events.
        for app_name in settings.INSTALLED_APPS:
            try:
                import_module('.management', app_name)
            except ImportError as exc:
                # This is slightly hackish. We want to ignore ImportErrors
                # if the "management" module itself is missing -- but we don't
                # want to ignore the exception if the management module exists
                # but raises an ImportError for some reason. The only way we
                # can do this is to check the text of the exception. Note that
                # we're a bit broad in how we check the text, because different
                # Python implementations may not use the same text.
                # CPython uses the text "No module named management"
                # PyPy uses "No module named myproject.myapp.management"
                msg = exc.args[0]
                if not msg.startswith('No module named') or 'management' not in msg:
                    raise

        db = options.get('database')
        connection = connections[db]
        cursor = connection.cursor()
        converter = connection.introspection.qname_converter
        # We might fetch the same table multiple times - once as qualified and
        # once as visible table (None, t). That is wanted, so that we can easily
        # see if a model with schema = None is installed, as well as if model with
        # locked schema is installed.
        tables = connection.introspection.all_qualified_names()
        
        # Get a list of already installed *models* so that references work right.
        seen_models = connection.introspection.installed_models(tables)
        created_models = set()
        pending_references = {}

        # Build the manifest of apps and models that are to be synchronized
        all_models = [
            (app.__name__.split('.')[-2],
                [m for m in models.get_models(app, include_auto_created=True)
                if router.allow_syncdb(db, m)])
            for app in models.get_apps()
        ]
        def model_installed(model):
            opts = model._meta
            return not ((converter(opts.qualified_name) in tables) or
                (opts.auto_created and converter(opts.auto_created._meta.qualified_name) in tables))

        manifest = SortedDict(
            (app_name, filter(model_installed, model_list))
            for app_name, model_list in all_models
        )

        # Create the tables for each model
        if verbosity >= 1:
            self.stdout.write("Creating tables ...\n")
        seen_schemas = connection.introspection.schema_names()
        seen_schemas = set([connection.introspection.identifier_converter(s)
                            for s in seen_schemas])
        for app_name, model_list in manifest.items():
            for model in model_list:
                # Create the model's database table, if it doesn't already exist.
                if verbosity >= 3:
                    self.stdout.write("Processing %s.%s model\n" % (app_name, model._meta.object_name))
                sql = []
                schema = connection.convert_schema(model._meta.qualified_name[0])
                if schema and schema not in seen_schemas:
                    q = connection.creation.sql_create_schema(schema, self.style)
                    if q:
                        sql.append(q)
                    seen_schemas.add(schema)
                table_sql, references = connection.creation.sql_create_model(model, self.style, seen_models)
                sql.extend(table_sql)
                seen_models.add(model)
                created_models.add(model)
                for refto, refs in references.items():
                    pending_references.setdefault(refto, []).extend(refs)
                    if refto in seen_models:
                        ref_sql = connection.creation.sql_for_pending_references(
                            refto, self.style, pending_references)
                        if ref_sql:
                            sql.extend(ref_sql)
                ref_sql = sql.extend(connection.creation.sql_for_pending_references(
                    model, self.style, pending_references))
                if ref_sql:
                    sql.extend(ref_sql)
                if verbosity >= 1 and sql:
                    if model._meta.db_schema:
                        self.stdout.write("Creating table %s.%s\n" % model._meta.qualified_name)
                    else:
                        self.stdout.write("Creating table %s\n" % model._meta.db_table)
                for statement in sql:
                    cursor.execute(statement)
                tables.append(connection.introspection.qname_converter(model._meta.qualified_name))

        transaction.commit_unless_managed(using=db)
        # We need to see if there are still some pending references left: this
        # is possible on backends where we must do cross-schema references
        # using different connections (hence also outside the above
        # transaction)
        if pending_references:
            # Pass the references to connection-specific handler.
            connection.creation.post_create_pending_references(pending_references)

        # Send the post_syncdb signal, so individual apps can do whatever they
        # need to do at this point.
        emit_post_sync_signal(created_models, verbosity, interactive, db)

        # The connection may have been closed by a syncdb handler.
        cursor = connection.cursor()

        # Install custom SQL for the app (but only if this
        # is a model we've just created)
        if verbosity >= 1:
            self.stdout.write("Installing custom SQL ...\n")
        for app_name, model_list in manifest.items():
            for model in model_list:
                if model in created_models:
                    custom_sql = custom_sql_for_model(model, self.style, connection)
                    if custom_sql:
                        if verbosity >= 2:
                            self.stdout.write("Installing custom SQL for %s.%s model\n" % (app_name, model._meta.object_name))
                        try:
                            for sql in custom_sql:
                                cursor.execute(sql)
                        except Exception as e:
                            self.stderr.write("Failed to install custom SQL for %s.%s model: %s\n" % \
                                                (app_name, model._meta.object_name, e))
                            if show_traceback:
                                traceback.print_exc()
                            transaction.rollback_unless_managed(using=db)
                        else:
                            transaction.commit_unless_managed(using=db)
                    else:
                        if verbosity >= 3:
                            self.stdout.write("No custom SQL for %s.%s model\n" % (app_name, model._meta.object_name))

        if verbosity >= 1:
            self.stdout.write("Installing indexes ...\n")
        # Install SQL indices for all newly created models
        for app_name, model_list in manifest.items():
            for model in model_list:
                if model in created_models:
                    index_sql = connection.creation.sql_indexes_for_model(model, self.style)
                    if index_sql:
                        if verbosity >= 2:
                            self.stdout.write("Installing index for %s.%s model\n" % (app_name, model._meta.object_name))
                        try:
                            for sql in index_sql:
                                cursor.execute(sql)
                        except Exception as e:
                            self.stderr.write("Failed to install index for %s.%s model: %s\n" % \
                                                (app_name, model._meta.object_name, e))
                            transaction.rollback_unless_managed(using=db)
                        else:
                            transaction.commit_unless_managed(using=db)

        # Load initial_data fixtures (unless that has been disabled)
        if load_initial_data:
            from django.core.management import call_command
            call_command('loaddata', 'initial_data', verbosity=verbosity,
                         database=db, skip_validation=True)
