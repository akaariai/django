from __future__ import absolute_import, unicode_literals

from django.db import IntegrityError
from django.test import TestCase

from .models import UpdatablePKModel, SingleFieldPK

class UpdatablePKTests(TestCase):

    def test_basic_update(self):
        m = UpdatablePKModel(code='code1', value='foo')
        m.save()
        m.code = 'code2'
        m.save()
        self.assertTrue(UpdatablePKModel.objects.filter(code='code2').exists())
        self.assertFalse(UpdatablePKModel.objects.filter(code='code1').exists())
        self.assertEqual(UpdatablePKModel.objects.get(pk='code2').value, 'foo')

    def test_conflicts(self):
        m = UpdatablePKModel(code='code1', value='foo')
        m2 = UpdatablePKModel(code='code2', value='bar')
        m.save()
        m2.save()
        m.pk = 'code2'
        with self.assertRaises(IntegrityError):
            m.save()

    def test_force_insert(self):
        m = UpdatablePKModel(code='code1', value='foo')
        m.save()
        m.pk = 'code2'
        m.save(force_insert=True)
        self.assertEqual(UpdatablePKModel.objects.count(), 2)
        m.pk = 'code3'
        m.save()
        self.assertTrue(UpdatablePKModel.objects.filter(pk='code1').exists())
        self.assertTrue(UpdatablePKModel.objects.filter(pk='code3').exists())
        self.assertEqual(UpdatablePKModel.objects.count(), 2)

    def test_single_field_update(self):
        s = SingleFieldPK(code='code1')
        s.save()
        s.pk = 'code2'
        s.save()
        self.assertFalse(SingleFieldPK.objects.filter(pk='code1').exists())
        self.assertTrue(SingleFieldPK.objects.filter(pk='code2').exists())
        self.assertEqual(SingleFieldPK.objects.count(), 1)
