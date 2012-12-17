from __future__ import absolute_import, unicode_literals

from datetime import datetime

from django.db.models import Q, Count
from django.test import TestCase
from django.utils.translation import activate, deactivate

from .models import Article, ArticleComment, ArticleTranslation


class ModelTest(TestCase):
    def setUp(self):
        self.a1 = Article.objects.create(headline='h1', pub_date=datetime.now(), data='d1')
        self.a2 = Article.objects.create(headline='h2', pub_date=datetime.now(), data='d2')
        self.c1 = ArticleComment.objects.create(headline='h1', pub_date=self.a1.pub_date, comment='c1')
        self.c2 = ArticleComment.objects.create(headline='h1', pub_date=self.a1.pub_date, comment='c2')
        self.c3 = ArticleComment.objects.create(headline='h2', pub_date=self.a2.pub_date, comment='c3')

    def test_basic_join(self):
        self.assertEqual(ArticleComment.objects.filter(article__data='d1').count(), 2)
        self.assertEqual(ArticleComment.objects.filter(article__data='d2').count(), 1)

    def test_basic_revjoin(self):
        self.assertEqual(Article.objects.filter(comments__comment='c1').count(), 1)
        self.assertEqual(Article.objects.filter(comments__comment__in=['c1', 'c3']).count(), 2)
        self.assertEqual(Article.objects.filter(comments__comment='c3').count(), 1)

    def test_translation_join(self):
        try:
            ArticleTranslation.objects.create(article=self.a1, lang='fi', title='Otsikko')
            ArticleTranslation.objects.create(article=self.a1, lang='en', title='Title')
            activate('fi')
            self.assertEqual(Article.objects.filter(translation__title='Otsikko').count(), 1)
            self.assertEqual(Article.objects.filter(translation__title='Title').count(), 0)
            activate('en')
            self.assertEqual(Article.objects.filter(translation__title='Otsikko').count(), 0)
            self.assertEqual(Article.objects.filter(translation__title='Title').count(), 1)
            # isnull works too (that is, we have proper left joins!)
            self.assertEqual(Article.objects.filter(
                Q(translation__title='Title') | Q(translation__isnull=True)).count(), 2)
            self.assertEqual(Article.objects.filter(
                Q(translation__title='Otsikko') | Q(translation__isnull=True)).count(), 1)
            self.assertEqual(Article.objects.aggregate(Count('translation'))['translation__count'], 1)
        finally:
            deactivate()

    def test_select_related(self):
        ArticleTranslation.objects.create(article=self.a1, lang='fi', title='Otsikko')
        ArticleTranslation.objects.create(article=self.a1, lang='en', title='Title')
        qs = Article.objects.select_related('translation').order_by('headline')
        try:
            with self.assertNumQueries(1):
                activate('fi')
                objs = list(qs)
                self.assertEqual(objs[0].translation.title, 'Otsikko')
                # Caching works
                self.assertIs(objs[0].translation.article, objs[0])
                self.assertIs(objs[1].translation, None)
            with self.assertNumQueries(1):
                activate('en')
                # .all() to get rid of the cache...
                objs = list(qs.all())
                self.assertEqual(objs[0].translation.title, 'Title')
                self.assertEqual(objs[1].translation, None)
            ArticleTranslation.objects.create(article=self.a2, lang='en', title='Title 2')
            # Some ordering stuff still...
            with self.assertNumQueries(1):
                objs = list(Article.objects.select_related('translation').order_by('translation__title'))
                self.assertEqual(objs[0].translation.title, 'Title')
                self.assertEqual(objs[1].translation.title, 'Title 2')
            with self.assertNumQueries(1):
                objs = list(Article.objects.select_related('translation').order_by('-translation__title'))
                self.assertEqual(objs[0].translation.title, 'Title 2')
                self.assertEqual(objs[1].translation.title, 'Title')
        finally:
            deactivate()
