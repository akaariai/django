# coding: utf-8
from django.db import models
from django.utils.encoding import python_2_unicode_compatible


@python_2_unicode_compatible
class Author(models.Model):
    name = models.CharField(max_length=100)
    age = models.IntegerField()
    friends = models.ManyToManyField('self', blank=True)

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class Publisher(models.Model):
    name = models.CharField(max_length=255)
    num_awards = models.IntegerField()

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class Book(models.Model):
    isbn = models.CharField(max_length=9)
    name = models.CharField(max_length=255)
    pages = models.IntegerField()
    rating = models.FloatField()
    price = models.DecimalField(decimal_places=2, max_digits=6)
    authors = models.ManyToManyField(Author)
    contact = models.ForeignKey(Author, related_name='book_contact_set')
    publisher = models.ForeignKey(Publisher)
    pubdate = models.DateField()

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class Store(models.Model):
    name = models.CharField(max_length=255)
    books = models.ManyToManyField(Book)
    original_opening = models.DateTimeField()
    friday_night_closing = models.TimeField()

    def __str__(self):
        return self.name


@python_2_unicode_compatible
class DepartmentStore(Store):
    chain = models.CharField(max_length=255)

    def __str__(self):
        return '%s - %s ' % (self.chain, self.name)


@python_2_unicode_compatible
class Company(models.Model):
    name = models.CharField(max_length=200)
    motto = models.CharField(max_length=200, null=True, blank=True)
    ticker_name = models.CharField(max_length=10, null=True, blank=True)
    description = models.CharField(max_length=200, null=True, blank=True)

    def __str__(self):
        return ('Company(name=%s, motto=%s, ticker_name=%s, description=%s)'
            % (self.name, self.motto, self.ticker_name, self.description)
        )
