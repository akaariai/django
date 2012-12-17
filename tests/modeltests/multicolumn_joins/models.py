"""
Note that these tests rely heavily on non-public APIs and are really hacky in
nature. So, if these are broken by changes it doesn't mean the change isn't
valid - fixing these tests is also an option...

What we are interested in is some way to generate multicolumn joins using the
ORM, not the specific way to do it.
"""
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.related import PathInfo
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import get_language

class FakeFKField(object):
    null = False

    @classmethod
    def get_path_info(cls, direct=True):
        if direct:
            opts = Article._meta
            target = Article._meta.get_field_by_name('id')[0]
            from_opts = ArticleComment._meta
        else:
            opts = ArticleComment._meta
            target = ArticleComment._meta.pk
            from_opts = Article._meta
        return [PathInfo(cls, target, from_opts, opts, cls, False, True)], opts, target, cls

    @classmethod
    def get_join_sql(cls, connection, qn, lhs_alias, rhs_alias, direct):
        # Note - we don't care about direct here - we have exactly the same
        # column names on both sides...
        lhs, rhs = qn(lhs_alias), qn(rhs_alias)
        headline, pub_date = qn('headline'), qn('pub_date')

        return ('%s.%s = %s.%s AND %s.%s = %s.%s' %
                (lhs, headline, rhs, headline, lhs, pub_date, rhs, pub_date)), []

class TranslationField(object):
    null = True
    name = 'translation'
    unique = True

    @classmethod
    def get_path_info(cls):
        opts = ArticleTranslation._meta
        target = ArticleTranslation._meta.pk
        from_opts = Article._meta
        return [PathInfo(cls, target, from_opts, opts, cls, False, False)], opts, target, target

    @classmethod
    def get_join_sql(cls, connection, qn, lhs_alias, rhs_alias, direct):
        lhs, rhs = qn(lhs_alias), qn(rhs_alias)
        lang = qn('lang')
        article_id = qn('article_id')
        id = qn('id')
        return ('%s.%s = %s.%s AND %s.%s = %%s' %
                (lhs, id, rhs, article_id, rhs, lang)), [get_language()]

    @classmethod
    def select_related_descend(cls, restricted, requested, only_load):
        if requested and 'translation' in requested:
            return True
        return restricted

    @classmethod
    def get_cache_name(cls):
        return 'translation'

    @classmethod
    def get_related_cache_name(cls):
        return 'article'

class WrappedMeta(object):
    def __init__(self, meta):
        self.__dict__['meta'] = meta

    def __getattr__(self, attr):
        return getattr(self.meta, attr)

    def __setattr__(self, attr, value):
        setattr(self.meta, attr, value)

class FakeRelObject(object):

    @classmethod
    def get_path_info(self):
        return FakeFKField.get_path_info(direct=False)

class ArticleMeta(WrappedMeta):

    def get_field_by_name(self, name):
        if name == 'comments':
            return FakeRelObject, None, False, True
        elif name == 'translation':
            return TranslationField, None, False, False
        else:
            return self.meta.get_field_by_name(name)

    def get_fields_with_model(self):
        return self.meta.get_fields_with_model() + ((TranslationField, None),)

class ArticleBase(ModelBase):
    def __new__(cls, name, bases, attrs):
        super_new = super(ArticleBase, cls).__new__(cls, name, bases, attrs)
        super_new._meta = ArticleMeta(super_new._meta)
        return super_new

@python_2_unicode_compatible
class Article(models.Model):
    __metaclass__ = ArticleBase
    headline = models.CharField(max_length=100, default='Default headline')
    pub_date = models.DateTimeField()
    data = models.TextField()

    class Meta:
        ordering = ('pub_date', 'headline')
        unique_together = (('headline', 'pub_date'),)

    def __str__(self):
        return self.headline


class ArticleCommentMeta(WrappedMeta):
    def get_field_by_name(self, name):
        if name == 'article':
            return FakeFKField, None, True, False
        else:
            return self.meta.get_field_by_name(name)

class ArticleCommentBase(ModelBase):
    def __new__(cls, name, bases, attrs):
        super_new = super(ArticleCommentBase, cls).__new__(cls, name, bases, attrs)
        super_new._meta = ArticleCommentMeta(super_new._meta)
        return super_new

class ArticleComment(models.Model):
    __metaclass__ = ArticleCommentBase

    headline = models.CharField(max_length=100)
    pub_date = models.DateTimeField()
    comment = models.TextField()

class ArticleTranslation(models.Model):
    article = models.ForeignKey(Article, related_name='translations')
    lang = models.CharField(max_length=2)
    title = models.CharField(max_length=100)

    class Meta:
        unique_together = (('article', 'lang'),)

TranslationField.model = ArticleTranslation
