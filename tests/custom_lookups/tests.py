# -*- encoding: utf-8 -*-
from __future__ import unicode_literals

import re

from django.db import connection
from django.db.backends.utils import add_implementation
from django.db.models import Sum, SimpleLookup, RefCol, Field, MultiRefCol, CharField, IntegerField
from django.test import TestCase
from unittest import skipUnless

from .models import Author, NotEqual, FakeNotEqual, CustomIntegerField, SubCustomIntegerField, Book
from .collate import Collate


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

    def test_add_implementation(self):
        CustomIntegerField.register_class_lookup(NotEqual)
        try:
            @add_implementation(NotEqual, connection.vendor)
            def overriden_equal(node, compiler):
                lhs, lhs_params = node.process_lhs(compiler, compiler.connection)
                rhs, rhs_params = node.process_rhs(compiler, compiler.connection)
                lhs_params.extend(rhs_params)
                return '%s = %s' % (lhs, rhs), lhs_params

            col_last_part = connection.ops.quote_name("age")
            self.assertIn('%s = 3' % col_last_part, str(Author.objects.filter(age__ne=3).query))
            self.assertIn('%s %% 3 = 3' % col_last_part, str(Author.objects.filter(age__div3__ne=3).query))
        finally:
            del connection.compile_implementations[NotEqual]

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

    @skipUnless(connection.vendor == 'postgresql',
                'Uses PostgreSQL specific SQL')
    def test_array_agg(self):
        # It is possible to create completely custom aggregate.
        class ArrayAgg(RefCol):
            is_aggregate = True
            output_type = Field()

            # If wanted, the converter can be created dynamically.
            @property
            def convert_value(self):
                inner_converter = self.col.output_type.convert_value
                if inner_converter:
                    def myconverter(value, field, connection):
                        return [inner_converter(v, connection) for v in value]
                    return myconverter
                return None

            def as_sql(self, qn, connection):
                inner_sql, params = self.col.as_sql(qn, connection)
                params.extend(params)
                return 'ARRAY_AGG(%s ORDER BY %s)' % (inner_sql, inner_sql), params

            class ArrayContainsLookup(SimpleLookup):
                lookup_type = 'contains_val'

                def as_sql(self, qn, connection):
                    if not isinstance(self.value, list):
                        self.value = [self.value]
                    lhs_sql, params = self.process_lhs(qn, connection)
                    rhs_sql, rhs_params = self.process_rhs(qn, connection)
                    params.extend(rhs_params)
                    return '%s @> %s' % (lhs_sql, rhs_sql), params

            class ArrayOverlapsLookup(SimpleLookup):
                lookup_type = 'overlaps'

                def as_sql(self, qn, connection):
                    if not isinstance(self.value, list):
                        self.value = [self.value]
                    lhs_sql, params = self.process_lhs(qn, connection)
                    rhs_sql, rhs_params = self.process_rhs(qn, connection)
                    params.extend(rhs_params)
                    return '%s && %s' % (lhs_sql, rhs_sql), params

            def get_lookup(self, lookup):
                if lookup == 'contains':
                    return self.ArrayContainsLookup
                if lookup == 'overlaps':
                    return self.ArrayOverlapsLookup
                raise LookupError("Lookup %s isn't supported by %s." %
                                  (lookup, self.__class__.__name__))

        self.a4 = Author.objects.create(age=4, name='a4')

        qs = Author.objects.values_list('age__div3').annotate(
            name_arr=ArrayAgg('name')
        ).order_by('age__div3')
        self.assertQuerysetEqual(
            qs,
            [
                (0, ['a3']),
                (1, ['a1', 'a4']),
                (2, ['a2']),
            ], lambda x: x)
        qs = Author.objects.values('age__div3').annotate(
            id_arr=ArrayAgg('id')
        ).order_by('age__div3')
        self.assertQuerysetEqual(
            qs,
            [
                {'age__div3': 0, 'id_arr': [self.a3.id]},
                {'age__div3': 1, 'id_arr': [self.a1.id, self.a4.id]},
                {'age__div3': 2, 'id_arr': [self.a2.id]},
            ], lambda x: x)
        res_qs = qs.filter(id_arr__contains=self.a1.id)
        self.assertQuerysetEqual(
            res_qs,
            [
                {'age__div3': 1, 'id_arr': [self.a1.id, self.a4.id]},
            ], lambda x: x)
        res_qs = qs.filter(id_arr__contains=[self.a1.id, self.a4.id])
        self.assertQuerysetEqual(
            res_qs,
            [
                {'age__div3': 1, 'id_arr': [self.a1.id, self.a4.id]},
            ], lambda x: x)
        res_qs = qs.filter(id_arr__contains=[self.a1.id, self.a2.id])
        self.assertQuerysetEqual(
            res_qs,
            [], lambda x: x)
        res_qs = qs.filter(id_arr__overlaps=[self.a2.id, self.a4.id])
        self.assertQuerysetEqual(
            res_qs,
            [
                {'age__div3': 1, 'id_arr': [self.a1.id, self.a4.id]},
                {'age__div3': 2, 'id_arr': [self.a2.id]},
            ], lambda x: x)

    def test_case_when_node(self):
        class RefSQL(MultiRefCol):
            EXTEND_PARAMS_MARKER = object()

            def __init__(self, sql, params, output_type):
                self.sql, self.params = sql, params
                results = re.findall('(%s)|({{\s*[\w_]+\s*}})', self.sql)
                self.param_groups = []
                self.lookups = []
                self.output_type = output_type
                params = list(reversed(params))
                for result in results:
                    if result[0]:
                        self.param_groups.append(params.pop())
                    else:
                        self.param_groups.append(self.EXTEND_PARAMS_MARKER)
                        self.lookups.append(result[1][2:-2].strip())
                self.sql = re.sub('%s', '%%s', self.sql)
                self.sql = re.sub('{{\s*[\w_]+\s*}}', '%s', self.sql)

            def as_sql(self, qn, connection):
                sql_parts = []
                params = []
                cols = list(reversed(self.cols))
                for param in self.param_groups:
                    if param is self.EXTEND_PARAMS_MARKER:
                        sql, sql_params = cols.pop().as_sql(qn, connection)
                        params.extend(sql_params)
                        sql_parts.append(sql)
                    else:
                        params.append(param)
                return self.sql % tuple(sql_parts), params
        casewhenagediv3 = RefSQL(
            """
            case when {{age__div3}} = 1 then %s /* 1 and 4 */
            when {{age}} = 2 then %s /* 2 */
            else %s end
            """, ['was1', 'was2', 'wasother'],
            output_type=CharField())
        qs = Author.objects.annotate(my_ref=casewhenagediv3).filter(my_ref__exact='wasother')
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].my_ref, 'wasother')
        self.assertEqual(qs[0].age, 3)
        qs = Author.objects.alias(my_ref=casewhenagediv3).filter(my_ref__exact='wasother')
        self.assertEqual(len(qs), 1)
        self.assertFalse(hasattr(qs[0], 'my_ref'))
        self.assertEqual(qs[0].age, 3)
        if_age_gte2 = RefSQL(
            """
            case when {{age}} >= 2 then %s
            else %s end
            """, [1, 0],
            output_type=IntegerField())
        qs = Author.objects.alias(if_age_gte2=if_age_gte2).aggregate(
            count_age_gte2=Sum('if_age_gte2'))
        self.assertEqual(qs['count_age_gte2'], 2)
        if_pages_gte_100 = RefSQL(
            """
            case when {{book__pages}} >= 100 then %s
            else %s end
            """, [1, 0],
            output_type=IntegerField())
        qs = Author.objects.alias(if_pages_gte_100=if_pages_gte_100).alias(
            count_pages_gte_100=Sum('if_pages_gte_100')
        ).filter(
            count_pages_gte_100__gte=1).order_by('count_pages_gte_100')
        self.assertEqual(len(qs), 0)
        Book.objects.create(pages=100, author=self.a1)
        Book.objects.create(pages=99, author=self.a2)
        Book.objects.create(pages=101, author=self.a3)
        Book.objects.create(pages=100, author=self.a3)
        new_qs = qs.all()
        self.assertQuerysetEqual(
            new_qs, [self.a1, self.a3], lambda x: x)

    @skipUnless(connection.vendor == 'postgresql' and connection.pg_version >= 90100,
                'Uses PostgreSQL 9.1+ specific SQL')
    def test_collate(self):
        # Needs collations fi_FI, POSIX, en_GB
        from django.db import connection
        cur = connection.cursor()
        cur.execute("select 1 from pg_collation where collname in %s",
                    (('fi_FI', 'POSIX', 'en_GB'),))
        if len(cur.fetchall()) < 3:
            return
        a1 = Author.objects.create(name='äxx', age=12)
        a2 = Author.objects.create(name='axx', age=12)
        a3 = Author.objects.create(name='bxx', age=12)
        b1 = Book.objects.create(author=a1, pages=123)
        b2 = Book.objects.create(author=a2, pages=123)
        b3 = Book.objects.create(author=a3, pages=123)
        base_qs = Book.objects.alias(
            author_name_fi=Collate('author__name', 'fi_FI'),
            author_name_en=Collate('author__name', 'en_GB'),
            author_name_posix=Collate('author__name', 'POSIX'),
        )
        self.assertQuerysetEqual(
            base_qs.order_by('author_name_fi'),
            [b2, b3, b1],  # a > b > ä in finnish collation
            lambda x: x)
        self.assertQuerysetEqual(
            base_qs.order_by('author_name_en'),
            [b2, b1, b3],  # a > ä > b in english collation
            lambda x: x)
        # Filters work, too
        # lower(Ä) != ä in POSIX collate
        self.assertEqual(base_qs.filter(author_name_posix__icontains='ä').count(), 0)
        # lower(Ä) == ä in fi collate
        self.assertEqual(base_qs.filter(author_name_fi__icontains='ä').count(), 1)
