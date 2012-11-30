from __future__ import absolute_import, unicode_literals

from django.db import IntegrityError
from django.test import TestCase

from .models import UpdatablePKModel, SingleFieldPK, TrackStateModel

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

class StateTrackingTests(TestCase):
    def test_basic(self):
        t = TrackStateModel(f1='foo', f2='foo', f3='foo')
        t.save()
        # Change the value of f2 and f3
        t2 = TrackStateModel(pk=t.pk, f1='foo', f2='bar', f3='bar')
        t2.save()
        t.f1 = 'baz'
        with self.assertNumQueries(1):
            t.save()
        self.assertEqual(TrackStateModel.objects.count(), 1)
        db_t = TrackStateModel.objects.get(pk=t.pk)
        # f1 was updated
        self.assertEqual(db_t.f1, 'baz')
        # f2 and f3 not (they weren't changed)
        self.assertEqual(db_t.f2, 'bar')
        self.assertEqual(db_t.f3, 'bar')
        with self.assertNumQueries(0):
            db_t.save() # No changes - no queries

    def test_deferred(self):
        t = TrackStateModel(f1='foo', f2='foo', f3='foo')
        t.save()
        # override f2 without telling t about this...
        t2 = TrackStateModel(id=t.pk, f1='foo', f2='foo', f3='fuu')
        t2.save()
        deferred_t = TrackStateModel.objects.only('f1').get(pk=t.pk)
        with self.assertNumQueries(0):
            deferred_t.save()
        deferred_t.f1 = 'bar'
        with self.assertNumQueries(1):
            deferred_t.save()
        # fetch f2 value
        deferred_t.f2
        with self.assertNumQueries(0):
            deferred_t.save()
        deferred_t.f2 = 'baz'
        with self.assertNumQueries(1):
            deferred_t.save()
        db_t = TrackStateModel.objects.get(pk=t.pk)
        self.assertEqual(db_t.f1, 'bar')
        self.assertEqual(db_t.f2, 'baz')
        self.assertEqual(db_t.f3, 'fuu')
