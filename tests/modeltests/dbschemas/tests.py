from __future__ import absolute_import

from .models import (SameName1, SameName2, M2MTable, PrefixCollision,
                     PrefixCollision2)

from django.core.management.sql import sql_flush, sql_all
from django.core.management.color import no_style
from django.db import transaction, IntegrityError, connection
from django.db.models.loading import get_app
from django.test import (TestCase, TransactionTestCase,
    skipUnlessDBFeature)

class SchemaTests(TestCase):
    def test_create(self):
        sn1 = SameName1.objects.create()
        self.assertEqual(SameName2.objects.count(), 0)
        SameName2.objects.create(fk=sn1)
        self.assertEqual(SameName1.objects.count(), 1)
    
    def test_update(self):
        sn1 = SameName1.objects.create(txt='foo')
        self.assertEqual(SameName1.objects.get(pk=sn1.pk).txt, 'foo')
        sn1.txt = 'bar'
        sn1.save()
        self.assertEqual(SameName1.objects.get(pk=sn1.pk).txt, 'bar')
        
    def test_fk(self):
        sn1 = SameName1.objects.create()
        sn2 = SameName1.objects.create()
        SameName2.objects.create(fk=sn1)
        SameName2.objects.create(fk=sn1)
        SameName2.objects.create(fk=sn2)
        self.assertEqual(SameName2.objects.filter(fk=sn1).count(), 2)
        self.assertEqual(SameName2.objects.filter(fk=sn2).count(), 1)
        self.assertEqual(SameName2.objects.select_related('fk').order_by('fk__pk')[0].fk.pk, sn1.pk)
        self.assertEqual(SameName2.objects.select_related('fk').order_by('fk__pk')[0].fk.pk, sn1.pk)
        self.assertEqual(SameName2.objects.order_by('fk__pk')[0].fk.pk, sn1.pk)
    
    def test_m2m(self):
        sn1 = SameName1.objects.create()
        sn2 = SameName1.objects.create()
        m1 = M2MTable.objects.create()
        m1.m2m.add(sn1)
        m1.m2m.add(sn2)
        M2MTable.objects.create()
        m1 = M2MTable.objects.filter(m2m__in=[sn1, sn2])[0]
        self.assertEquals(list(m1.m2m.order_by('pk')), [sn1, sn2])

    def test_sql_flush(self):
        """
        Test that sql_flush contains some key pieces of SQL.
        """
        qname = connection.qname(SameName2)
        style = no_style()
        flush_output = sql_flush(style, connection)
        found = False
        for sql in flush_output:
            if qname in sql:
                found = True
                break
        self.assertTrue(found, "Table '%s' not found in sql_flush output." % qname)

    def test_sql_all(self):
        """
        Test that sql_all contains the create schema statements.
        """
        schema = connection.convert_schema(SameName2._meta.db_schema)
        create_schema_sql = connection.creation.sql_create_schema(schema, no_style())
        found = create_schema_sql in sql_all(get_app('dbschemas'), no_style(),
                                             connection)
        self.assertTrue(found or not create_schema_sql,
                        'SQL for creating schemas not found from sql_all output')

    def test_prefix_collisions(self):
        try:
            orig_schema = connection.settings_dict['SCHEMA']
            connection.settings_dict['SCHEMA'] = 'foo'
            self.assertNotEqual(connection.qname(PrefixCollision), connection.qname(PrefixCollision2))
        finally:
            connection.settings_dict['SCHEMA'] = orig_schema


class TransactionalSchemaTests(TransactionTestCase):
    @skipUnlessDBFeature('supports_transactions')
    @skipUnlessDBFeature('supports_foreign_keys')
    def test_foreign_keys(self):
        """
        Test that creating a model with non-matched cross-schema foreign
        key results in foreign key violation.
        """
        @transaction.commit_on_success
        def invalid_fk():
            SameName2.objects.create(fk_id=-1)
        self.assertRaises(IntegrityError, invalid_fk)
