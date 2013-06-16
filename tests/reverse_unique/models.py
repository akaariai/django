from datetime import date

from django.db import models
from django.db.models import Q, F
from django.utils.translation import get_language
from django.db.models.fields.reverse_unique import ReverseUnique

class Article(models.Model):
    pub_date = models.DateField()
    active_translation = ReverseUnique(
        "ArticleTranslation", filters=Q(lang=get_language),
        related_field='article')

class ArticleTranslation(models.Model):
    article = models.ForeignKey(Article)
    lang = models.CharField(max_length=2)
    title = models.CharField(max_length=100)
    abstract = models.CharField(max_length=100, null=True)
    body = models.TextField()

    class Meta:
        unique_together = ('article', 'lang')


class DefaultTranslationArticle(models.Model):
    pub_date = models.DateField()
    default_lang = models.CharField(max_length=2)
    active_translation = ReverseUnique(
        "DefaultTranslationArticleTranslation", filters=Q(lang=get_language),
        related_field='article')
    default_translation = ReverseUnique(
        "DefaultTranslationArticleTranslation", filters=Q(lang=F('article__default_lang')),
        related_field='article')

class DefaultTranslationArticleTranslation(models.Model):
    article = models.ForeignKey(DefaultTranslationArticle)
    lang = models.CharField(max_length=2)
    title = models.CharField(max_length=100)
    abstract = models.CharField(max_length=100, null=True)
    body = models.TextField()

    class Meta:
        unique_together = ('article', 'lang')


class Guest(models.Model):
    name = models.CharField(max_length=100)

class Reservation(models.Model):
    room = models.ForeignKey("Room")
    guest = models.ForeignKey(Guest)
    from_date = models.DateField()
    until_date = models.DateField(null=True)  # NULL means reservation "forever".

class Room(models.Model):
    current_reservation = ReverseUnique(
        Reservation, related_field='room',
        filters=(Q(from_date__lte=date.today) & (
            Q(until_date__gte=date.today) | Q(until_date__isnull=True))))
