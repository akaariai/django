from __future__ import unicode_literals

from django.db import connection
from django.db.models import Sum
from django.test import TestCase
from unittest import skipUnless

from .models import Author, NotEqual, FakeNotEqual, CustomIntegerField, SubCustomIntegerField


class CustomColumnsTests(TestCase):
    def setUp(self):
        self.a1 = Author.objects.create(name='a1', age=1)
        self.a2 = Author.objects.create(name='a2', age=2)
        self.a3 = Author.objects.create(name='a3', age=3)

    def test_div2_lookup(self):
        self.assertQuerysetEqual(
            Author.objects.filter(age__div2=1), [self.a1, self.a3], lambda x: x)
        self.assertQuerysetEqual(
            Author.objects.filter(age__div2=0), [self.a2], lambda x: x)

    def test_lookup_override(self):
        CustomIntegerField.register_class_lookup(NotEqual)
        self.assertQuerysetEqual(
            Author.objects.filter(age__ne=1), [self.a2, self.a3], lambda x: x)
        SubCustomIntegerField.register_class_lookup(FakeNotEqual)
        self.assertQuerysetEqual(
            Author.objects.filter(age__ne=1), [self.a1], lambda x: x)
        Author._meta.get_field('age').register_lookup(NotEqual)
        self.assertQuerysetEqual(
            Author.objects.filter(age__ne=1), [self.a2, self.a3], lambda x: x)

    def test_nested_lookup(self):
        self.assertQuerysetEqual(
            Author.objects.filter(age__div3__lte=1), [self.a1, self.a3], lambda x: x)
        self.assertQuerysetEqual(
            Author.objects.filter(age__div3__gte=2), [self.a2], lambda x: x)
        self.assertQuerysetEqual(
            Author.objects.filter(age__div3__isnull=True), [], lambda x: x)
        self.assertQuerysetEqual(
            Author.objects.filter(age__div3__in=[1, 2]), [self.a1, self.a2], lambda x: x)
        with self.assertNumQueries(0):
            self.assertQuerysetEqual(
                Author.objects.filter(age__div3__in=[]), [], lambda x: x)

    def test_values_list(self):
        self.assertQuerysetEqual(
            Author.objects.values_list('age__div3', flat=True),
            [1, 2, 0], lambda x: x)

    def test_values(self):
        self.assertQuerysetEqual(
            Author.objects.values('age__div3', 'age'),
            [
                {'age__div3': 1, 'age': 1},
                {'age__div3': 2, 'age': 2},
                {'age__div3': 0, 'age': 3}
            ],
            lambda x: x
        )

    def test_annotate(self):
        self.assertQuerysetEqual(
            Author.objects.annotate(div3_sum=Sum('age__div3')),
            [1, 2, 0], lambda x: x.div3_sum)

    def test_aggregate(self):
        self.assertEqual(
            Author.objects.aggregate(div3_sum=Sum('age__div3')),
            {'div3_sum': 3})

    def test_order_by(self):
        self.assertQuerysetEqual(
            Author.objects.order_by('age__div3'),
            [self.a3, self.a1, self.a2],
            lambda x: x)

    @skipUnless(connection.vendor == 'sqlite',
                'Case insensitive order is database dependent')
    def test_order_by_lower(self):
        Author.objects.all().delete()
        a1 = Author.objects.create(name='A1', age=1)
        a2 = Author.objects.create(name='a1', age=2)
        a3 = Author.objects.create(name='A1', age=3)
        a4 = Author.objects.create(name='a1', age=4)
        self.assertQuerysetEqual(
            Author.objects.order_by('name__lower', 'age'),
            [a1, a2, a3, a4],
            lambda x: x)
        self.assertQuerysetEqual(
            Author.objects.order_by('name'),
            [a1, a3, a2, a4],
            lambda x: x)
