from __future__ import unicode_literals

import datetime
import os
import gzip
import zipfile
from optparse import make_option

from django.conf import settings
from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import (connections, router, transaction, DEFAULT_DB_ALIAS,
      IntegrityError, DatabaseError)
from django.db.models import get_apps
from django.utils.encoding import force_text
from itertools import product

try:
    import bz2
    has_bz2 = True
except ImportError:
    has_bz2 = False

class SingleZipReader(zipfile.ZipFile):
    def __init__(self, *args, **kwargs):
        zipfile.ZipFile.__init__(self, *args, **kwargs)
        if settings.DEBUG:
            assert len(self.namelist()) == 1, "Zip-compressed fixtures must contain only one file."

    def read(self):
        return zipfile.ZipFile.read(self, self.namelist()[0])

compression_types = {
    None:   open,
    'gz':   gzip.GzipFile,
    'zip':  SingleZipReader
}
if has_bz2:
    compression_types['bz2'] = bz2.BZ2File

def humanize(dirname):
    return "'%s'" % dirname if dirname else 'absolute path'


class Command(BaseCommand):
    help = 'Installs the named fixture(s) in the database.'
    args = "fixture [fixture ...]"

    option_list = BaseCommand.option_list + (
        make_option('--database', action='store', dest='database',
            default=DEFAULT_DB_ALIAS, help='Nominates a specific database to load '
                'fixtures into. Defaults to the "default" database.'),
    )

    def find_fixture_files(self, fixture_labels, using, verbosity):
        """
        Given a list of fixture labels to load, this command will return
        a list of absolute paths for those fixtures.
        """
        app_module_paths = []
        for app in get_apps():
            if hasattr(app, '__path__'):
                # It's a 'models/' subpackage
                for path in app.__path__:
                    app_module_paths.append(path)
            else:
                # It's a models.py module
                app_module_paths.append(app.__file__)


        app_fixtures = [os.path.join(os.path.dirname(path), 'fixtures') for path in app_module_paths]
        # Pairs of (fixture label, all combos to check about this label)
        # The combos are products of different compression formats,
        # serializer formats and the db we are using + no DB.
        filenames_to_check = []
        for label in fixture_labels:
            parts = label.split('.')
            # Pick the compression type to use from the label.
            if len(parts) > 1 and parts[-1] in compression_types:
                compression_formats = [parts[-1]]
                parts = parts[:-1]
            else:
                # None defined, check all available compression types.
                compression_formats = compression_types.keys()

            # Pick the serializer format from the label.
            if len(parts) == 1:
                # None defined, use all available serializer formats.
                fixture_name = parts[0]
                formats = serializers.get_public_serializer_formats()
            else:
                fixture_name, format = '.'.join(parts[:-1]), parts[-1]
                if format in serializers.get_public_serializer_formats():
                    formats = [format]
                else:
                    formats = []

            if formats:
                if verbosity >= 2:
                    self.stdout.write("Loading '%s' fixtures..." % fixture_name)
            else:
                raise CommandError(
                    "Problem installing fixture '%s': %s is not a known serialization format." %
                        (fixture_name, format))
            # Produce the combos.
            label_combos = (label, [])
            for combo in product([using, None], formats, compression_formats):
                database, format, compression_format = combo
                file_name = '.'.join(
                    p for p in [
                        fixture_name, database, format, compression_format
                    ]
                    if p
                )
                label_combos[1].append((file_name, format, compression_format))
            filenames_to_check.append(label_combos)

        # OK, now we know what file names we are looking for. Lets see if we can find
        # these filenames.
        fixture_dirs = app_fixtures + list(settings.FIXTURE_DIRS) + ['']
        filenames = []
        for label, combos in filenames_to_check:
            if os.path.isabs(label):
                dirs = [label]
            else:
                dirs = fixture_dirs
            for fixture_dir in dirs:
                label_found = False
                if verbosity >= 2:
                    self.stdout.write("Checking %s for fixtures..." % humanize(fixture_dir))
                try:
                    files = set(os.listdir(fixture_dir))
                except OSError:
                    files = [fixture_dir]
                for fname, format, compression_format in combos:
                    if verbosity >= 3:
                        self.stdout.write("Trying %s for %s fixture '%s'..." %
                            (humanize(fixture_dir), fname, label))
                    if fname in files:
                        if label_found:
                            raise CommandError("Multiple fixtures named '%s' in %s. Aborting." %
                                (fixture_name, humanize(fixture_dir)))
                        label_found = True
                        filenames.append((label, os.path.join(fixture_dir, fname),
                                               format, compression_format))
                    elif verbosity >= 2:
                        self.stdout.write("No %s fixture '%s' in %s." %
                                          (format, fixture_name, humanize(fixture_dir)))
        return filenames

    def handle(self, *fixture_labels, **options):

        if not len(fixture_labels):
            raise CommandError(
                "No database fixture specified. Please provide the path of at "
                "least one fixture in the command line."
            )
        using = options.get('database')
        verbosity = int(options.get('verbosity'))
        fixture_files = self.find_fixture_files(fixture_labels, using, verbosity)
        connection = connections[using]
        # commit is a stealth option - it isn't really useful as
        # a command line option, but it can be useful when invoking
        # loaddata from within another script.
        # If commit=True, loaddata will use its own transaction;
        # if commit=False, the data load SQL will become part of
        # the transaction in place when loaddata was invoked.
        commit = options.get('commit', True)

        # Keep a count of the installed objects and fixtures
        loaded_object_count = 0
        fixture_object_count = 0
        models = set()


        # Get a cursor (even though we don't need one yet). This has
        # the side effect of initializing the test database (if
        # it isn't already initialized).
        cursor = connection.cursor()

        # Start transaction management. All fixtures are installed in a
        # single transaction to ensure that all references are resolved.
        if commit:
            transaction.commit_unless_managed(using=using)
            transaction.enter_transaction_management(using=using)
            transaction.managed(True, using=using)

        try:
            with connection.constraint_checks_disabled():
                for label, fname, format, compression_format in fixture_files:
                    objects_in_fixture = 0
                    loaded_objects_in_fixture = 0
                    open_method = compression_types[compression_format]
                    fixture = open_method(fname, 'r')
                    if verbosity >= 2:
                         self.stdout.write("Installing %s fixture '%s' from %s." %
                            (format, label, humanize(os.path.split(fname)[0])))
                    objects = serializers.deserialize(format, fixture, using=using)

                    for obj in objects:
                        objects_in_fixture += 1
                        if router.allow_syncdb(using, obj.object.__class__):
                            loaded_objects_in_fixture += 1
                            models.add(obj.object.__class__)
                            try:
                                obj.save(using=using)
                            except (DatabaseError, IntegrityError) as e:
                                e.args = ("Could not load %(app_label)s.%(object_name)s(pk=%(pk)s): %(error_msg)s" % {
                                        'app_label': obj.object._meta.app_label,
                                        'object_name': obj.object._meta.object_name,
                                        'pk': obj.object.pk,
                                        'error_msg': force_text(e)
                                    },)
                                raise

                    loaded_object_count += loaded_objects_in_fixture
                    fixture_object_count += objects_in_fixture
                    # If the fixture we loaded contains 0 objects, assume that an
                    # error was encountered during fixture loading.
                    if objects_in_fixture == 0:
                        raise CommandError(
                            "No fixture data found for '%s'. (File format may be invalid.)" %
                                (label))
                """
                except Exception as e:
                    if not isinstance(e, CommandError):
                        e.args = ("Problem installing fixture '%s': %s" % (full_path, e),)
                    raise
                finally:
                    fixture.close()
                """

            # Since we disabled constraint checks, we must manually check for
            # any invalid keys that might have been added
            table_names = [model._meta.db_table for model in models]
            try:
                connection.check_constraints(table_names=table_names)
            except Exception as e:
                e.args = ("Problem installing fixtures: %s" % e,)
                raise

        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:
            if commit:
                transaction.rollback(using=using)
                transaction.leave_transaction_management(using=using)
            raise

        # If we found even one object in a fixture, we need to reset the
        # database sequences.
        if loaded_object_count > 0:
            sequence_sql = connection.ops.sequence_reset_sql(no_style(), models)
            if sequence_sql:
                if verbosity >= 2:
                    self.stdout.write("Resetting sequences\n")
                for line in sequence_sql:
                    cursor.execute(line)

        if commit:
            transaction.commit(using=using)
            transaction.leave_transaction_management(using=using)

        if verbosity >= 1:
            if fixture_object_count == loaded_object_count:
                self.stdout.write("Installed %d object(s) from %d fixture(s)" % (
                    loaded_object_count, len(fixture_files)))
            else:
                self.stdout.write("Installed %d object(s) (of %d) from %d fixture(s)" % (
                    loaded_object_count, fixture_object_count, len(fixture_files)))

        # Close the DB connection. This is required as a workaround for an
        # edge case in MySQL: if the same connection is used to
        # create tables, load data, and query, the query can return
        # incorrect results. See Django #7572, MySQL #37735.
        if commit:
            connection.close()
