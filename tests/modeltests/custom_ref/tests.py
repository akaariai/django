from __future__ import absolute_import, unicode_literals

from datetime import datetime

from django.test import TestCase

from .models import Article, ArticleTranslation

from django.utils.translation import activate, deactivate


class CustomRefTests(TestCase):
    def setUp(self):
        self.a1 = Article.objects.create(pub_date=datetime.now())
        self.a1_trans_fi = ArticleTranslation.objects.create(
            article=self.a1, headline='foo', lang='fi')
        self.a1_trans_fr = ArticleTranslation.objects.create(
            article=self.a1, headline='le foo', lang='fr')
        self.a2 = Article.objects.create(pub_date=datetime.now())
        self.a2_trans_fi = ArticleTranslation.objects.create(
            article=self.a2, headline='bar', lang='fi')

    def tearDown(self):
        deactivate()

    def test_filter(self):
        activate('fi')
        qs = Article.objects.filter(translation__headline__icontains='foo')
        self.assertTrue('INNER' in str(qs.query))
        self.assertTrue(len(qs) == 1)
        self.assertTrue(self.a1 in qs)

    def test_select_related(self):
        qs = Article.objects.select_related('translation')
        activate('fi')
        self.assertTrue(ArticleTranslation.objects.filter(lang='fi').count() == 2)
        with self.assertNumQueries(1):
            self.assertTrue(len(qs) == 2)
            self.assertTrue(qs[0].translation.headline == 'foo')
            self.assertTrue(qs[1].translation.headline == 'bar')
        activate('fr')
        # Clone the query so that we aren't using the result cache from previous iteration.
        qs = qs.all()
        with self.assertNumQueries(1):
            self.assertTrue(len(qs) == 2)
            self.assertTrue(qs[0].translation.headline == 'le foo')
            self.assertTrue(qs[1].translation is None)

    def test_order_by(self):
        activate('fi')
        qs = Article.objects.order_by('translation__headline')
        self.assertTrue(qs[0] == self.a2)
        self.assertTrue(qs[1] == self.a1)
