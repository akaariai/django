"""
1. Bare-bones model

This is a basic model with only two non-primary-key fields.
"""
from django.db import models
from django.db.models.options import Options
from django.db.models.related import PathInfo
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import get_language

class TranslationFK(object):
    def __init__(self, from_model, to_model):
        self.from_opts = from_model._meta
        self.to_opts = to_model._meta
        self.model = from_model
        self.unique = True
        self.null = True
        self.name = 'translation'

    def get_path_info(self):
        return ([PathInfo(self, self.to_opts.get_field('article'), self.from_opts, self.to_opts,
                         self, False, False)], self.to_opts, self.to_opts.get_field('article'), self)

    def get_extra_join_sql(self, connection, qn, lhs, rhs):
        return ' AND %s.%s = %%s' % (rhs, qn('lang')), [get_language()]

    @property
    def column(self):
        return self.from_opts.pk.column
    
    def select_related_descend(cls, restricted, requested, only_load):
        if requested and 'translation' in requested:
            return True
        return restricted

    def get_cache_name(self):
        return 'translation'

    def get_related_cache_name(self):
        return 'article'

class TranslatableMeta(Options):
    def get_path_info(self, name, allow_explicit_fk, fail_lookup_callback):
        if name == 'translation':
            path, opts, target, final_field = TranslationFK(Article, ArticleTranslation).get_path_info()
            return opts, final_field, target, path, False
        return super(TranslatableMeta, self).get_path_info(name, allow_explicit_fk, fail_lookup_callback)

    def get_fields_with_model(self):
        return super(TranslatableMeta, self).get_fields_with_model() + ((TranslationFK(Article, ArticleTranslation), None),)

@python_2_unicode_compatible
class Article(models.Model):
    pub_date = models.DateTimeField()

    class Meta:
        ordering = ('pub_date',)

    def __str__(self):
        return self.headline
Article._meta.__class__ = TranslatableMeta

class ArticleTranslation(models.Model):
    article = models.ForeignKey(Article, related_name='translations')
    lang = models.CharField(max_length=2)
    headline = models.CharField(max_length=100)

    class Meta:
        unique_together = [
            ['article', 'lang']
        ]
