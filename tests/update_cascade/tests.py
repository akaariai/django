from __future__ import unicode_literals

from django.db import DEFAULT_DB_ALIAS
from django.db.models.update import Collector
from django.test import TestCase

from .models import (
    ModelA, ModelB, Tree, RecursiveRef1, RecursiveRef2, Country,
    City, Street)

class UpdateCascadeLowLevelTests(TestCase):
    def test_cascade_basic(self):
        a1 = ModelA.objects.create(a_field='foo1')
        a2 = ModelA.objects.create(a_field='foo2')
        ModelB.objects.create(fk=a1)
        ModelB.objects.create(fk=a1)
        ModelB.objects.create(fk=a2)
        collector = Collector(DEFAULT_DB_ALIAS)
        collector.collect(
            ModelB._meta.get_field('fk'),
            ['foo1'], {'fk_id': 'bar'})
        collector.update()
        self.assertFalse(ModelB.objects.filter(fk='foo1').exists())
        self.assertEqual(ModelB.objects.filter(fk='foo2').count(), 1)
        self.assertEqual(ModelB.objects.filter(fk='bar').count(), 2)

    def test_cascade_tree(self):
        root = Tree.objects.create(name='root')
        root_c1 = Tree.objects.create(name='root_c1', parent=root)
        Tree.objects.create(name='root_c1_c1', parent=root_c1)
        root_c2 = Tree.objects.create(name='root_c2', parent=root)
        Tree.objects.create(name='root_c2_c1', parent=root_c2)
        collector = Collector(DEFAULT_DB_ALIAS)
        collector.collect_field_update(
            Tree._meta.get_field('name'),
            ['root'], {'name': 'new_root'})
        Tree.objects.filter(name='root').update(name='new_root')
        collector.update()
        self.assertTrue(
            Tree.objects.filter(name='new_root').exists())
        self.assertEqual(
            Tree.objects.filter(parent='new_root').count(), 2)

    def test_cascade_recursive(self):
        rv1 = RecursiveRef1.objects.create(name='foo')
        rv2 = RecursiveRef2.objects.create(fk=rv1)
        RecursiveRef1.objects.update(rev_fk=rv2)
        collector = Collector(DEFAULT_DB_ALIAS)
        collector.collect_field_update(
            RecursiveRef1._meta.get_field('name'), [rv1.name],
            {'name': 'new_name'})
        collector.update()

        self.assertQuerysetEqual(
            RecursiveRef1.objects.values_list('name', 'rev_fk'),
            [('new_name', 'new_name')], lambda x: x)
        self.assertQuerysetEqual(
            RecursiveRef2.objects.values_list('fk', flat=True),
            ['new_name'], lambda x: x)

    def test_composite_update(self):
        finland = Country.objects.create(name='Finland')
        usa = Country.objects.create(name='USA')
        helsinki = City.objects.create(name='Helsinki', country=finland)
        espoo = City.objects.create(name='Espoo', country=finland)
        washington = City.objects.create(name='Washington', country=usa)
        mannerh = Street.objects.create(city=helsinki, name='Mannerh.')
        armas_lk = Street.objects.create(city=espoo, name='Armas_lk.')
        maple_street = Street.objects.create(city=washington, name='Maple Street')
        collector = Collector(DEFAULT_DB_ALIAS)
        collector.collect_field_update(
            Country._meta.get_field('name'), ['Finland'],
            {'name': 'Suomi'})
        collector.update()
        self.assertEqual(
            Street.objects.get(pk=mannerh.pk).city_country, 'Suomi')

class SaveCascadeTests(TestCase):
    def test_save_cascade(self):
        finland = Country.objects.create(name='Finland')
        usa = Country.objects.create(name='USA')
        helsinki = City.objects.create(name='Helsinki', country=finland)
        espoo = City.objects.create(name='Espoo', country=finland)
        washington = City.objects.create(name='Washington', country=usa)
        mannerh = Street.objects.create(city=helsinki, name='Mannerh.')
        armas_lk = Street.objects.create(city=espoo, name='Armas_lk.')
        maple_street = Street.objects.create(city=washington, name='Maple Street')
        finland.name = 'Suomi'
        finland.save()
        self.assertEqual(
            Street.objects.get(pk=mannerh.pk).city_country, 'Suomi')
