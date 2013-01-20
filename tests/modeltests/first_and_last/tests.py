from __future__ import absolute_import

from datetime import datetime

from django.test import TestCase

from .models import Article

class FirstAndLastTests(TestCase):
    def setUp(self):
        self.a1 = Article.objects.create(
            id=1, headline='An article', pub_date=datetime(2006, 7, 28))
        self.a2 = Article.objects.create(
            id=2, headline='Second article', pub_date=datetime(2005, 1, 28))
        self.a3 = Article.objects.create(
            id=3, headline='Also an article', pub_date=datetime(2005, 7, 28))

    def test_no_match(self):
        # First and last should return None when no object is found
        self.assertEqual(
            Article.objects.first(pub_date__year=2012),
            None,
        )
        self.assertEqual(
            Article.objects.last(pub_date__year=2012),
            None,
        )

    def test_no_ordering(self):
        # If there is no ordering, then first/last by PK
        self.assertEqual(
            Article.objects.order_by().first(),
            self.a1
        )
        self.assertEqual(
            Article.objects.order_by().last(),
            self.a3
        )

    def test_multiple_matches(self):
        # First/last should return the first object when multiple objects
        # are found (first/last by model's default ordering as no other
        # ordering is defined)
        self.assertEqual(
            Article.objects.first(pub_date__year=2005),
            self.a2,
        )
        self.assertEqual(
            Article.objects.last(pub_date__year=2005),
            self.a3,
        )

    def test_custom_ordering(self):
        # The default ordering can be overridden.
        aaa = Article.objects.create(
            id=4, headline='AAA', pub_date=datetime(2005, 5, 5))
        zzz = Article.objects.create(
            id=5, headline='ZZZ', pub_date=datetime(2005, 5, 5))
        self.assertEqual(
            Article.objects.order_by('headline').first(pub_date__year=2005),
            aaa,
        )
        self.assertEqual(
            Article.objects.order_by('headline').last(pub_date__year=2005),
            zzz,
        )

    def test_extra_ordering(self):
        # .extra() ordering works too (this is mostly interesting in the
        # reverse case)
        self.assertEqual(
            Article.objects.extra(order_by=('headline',)).first(),
            self.a3,
        )
        self.assertEqual(
            Article.objects.extra(order_by=('headline',)).last(),
            self.a2,
        )
