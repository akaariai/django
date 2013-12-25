from __future__ import unicode_literals
import datetime

from django.db.models import (
    Sum, Count,
    F, Value,
    IntegerField, BooleanField)
from django.db.models.fields import FieldDoesNotExist
from django.test import TestCase

from .models import Author, Publisher, Book, Store, DepartmentStore  # NOQA


class NonAggregateAnnotationTestCase(TestCase):
    fixtures = ["annotations.json"]

    def test_basic_annotation(self):
        books = Book.objects.annotate(
            is_book=Value(1, output_type=IntegerField()))
        for book in books:
            self.assertEqual(book.is_book, 1)

    def test_basic_f_annotation(self):
        books = Book.objects.annotate(another_rating=F('rating'))
        for book in books:
            self.assertEqual(book.another_rating, book.rating)

    def test_joined_annotation(self):
        books = Book.objects.select_related('publisher').annotate(
            num_awards=F('publisher__num_awards'))
        for book in books:
            self.assertEqual(book.num_awards, book.publisher.num_awards)

    def test_annotate_with_aggregation(self):
        books = Book.objects.annotate(
            is_book=Value(1, output_type=IntegerField()),
            rating_count=Count('rating'))
        for book in books:
            self.assertEqual(book.is_book, 1)
            self.assertEqual(book.rating_count, 1)

    def test_aggregate_over_annotation(self):
        agg = Author.objects.annotate(other_age=F('age')).aggregate(otherage_sum=Sum('other_age'))
        other_agg = Author.objects.aggregate(age_sum=Sum('age'))
        self.assertEqual(agg['otherage_sum'], other_agg['age_sum'])

    def test_filter_annotation(self):
        books = Book.objects.annotate(
            is_book=Value(1, output_type=IntegerField())
        ).filter(is_book=1)
        for book in books:
            self.assertEqual(book.is_book, 1)

    def test_filter_annotation_with_f(self):
        books = Book.objects.annotate(
            other_rating=F('rating')
        ).filter(other_rating=3.5)
        for book in books:
            self.assertEqual(book.other_rating, 3.5)

    def test_update_with_annotation(self):
        book_preupdate = Book.objects.get(pk=2)
        Book.objects.annotate(other_rating=F('rating') - 1).update(rating=F('other_rating'))
        book_postupdate = Book.objects.get(pk=2)
        self.assertEqual(book_preupdate.rating - 1, book_postupdate.rating)

    def test_annotation_with_m2m(self):
        books = Book.objects.annotate(author_age=F('authors__age')).filter(pk=1).order_by('author_age')
        self.assertEqual(books[0].author_age, 34)
        self.assertEqual(books[1].author_age, 35)

    def test_annotation_reverse_m2m(self):
        books = Book.objects.annotate(
            store_name=F('store__name')).filter(
            name='Practical Django Projects').order_by(
            'store_name')

        self.assertQuerysetEqual(
            books, [
                'Amazon.com',
                'Books.com',
                'Mamma and Pappa\'s Books'
            ],
            lambda b: b.store_name
        )

    def test_values_annotation(self):
        """
        Annotations can reference fields in a values clause,
        and contribute to an existing values clause.
        """
        # annotate references a field in values()
        qs = Book.objects.values('rating').annotate(other_rating=F('rating') - 1)
        book = qs.get(pk=1)
        self.assertEqual(book['rating'] - 1, book['other_rating'])

        # filter refs the annotated value
        book = qs.get(other_rating=4)
        self.assertEqual(book['other_rating'], 4)

        # can annotate an existing values with a new field
        book = qs.annotate(other_isbn=F('isbn')).get(other_rating=4)
        self.assertEqual(book['other_rating'], 4)
        self.assertEqual(book['other_isbn'], '155860191')

    def test_defer_annotation(self):
        """
        Deferred attributes can be referenced by an annotation,
        but they are not themselves deferred, and can not be deferred.
        """
        qs = Book.objects.defer('rating').annotate(other_rating=F('rating') - 1)

        with self.assertNumQueries(2):
            book = qs.get(other_rating=4)
            self.assertEqual(book.rating, 5)
            self.assertEqual(book.other_rating, 4)

        with self.assertRaises(FieldDoesNotExist):
            book = qs.defer('other_rating').get(other_rating=4)

    def test_mti_annotations(self):
        """
        Fields on an inherited model can be referenced by an
        annotated field.
        """
        d = DepartmentStore.objects.create(
            name='Angus & Robinson',
            original_opening=datetime.date(2014, 3, 8),
            friday_night_closing=datetime.time(21, 00, 00),
            chain='Westfield'
        )

        books = Book.objects.filter(rating__gt=4)
        for b in books:
            d.books.add(b)

        qs = DepartmentStore.objects.annotate(
            other_name=F('name'),
            other_chain=F('chain'),
            is_open=Value(True, BooleanField()),
            book_isbn=F('books__isbn')
        ).select_related('store').order_by('book_isbn').filter(chain='Westfield')

        self.assertQuerysetEqual(
            qs, [
                ('Angus & Robinson', 'Westfield', True, '155860191'),
                ('Angus & Robinson', 'Westfield', True, '159059725')
            ],
            lambda d: (d.other_name, d.other_chain, d.is_open, d.book_isbn)
        )
