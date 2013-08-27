"""
17. Custom column/table names

If your database column name is different than your model attribute, use the
``db_column`` parameter. Note that you'll use the field's name, not its column
name, in API usage.

If your database table name is different than your model name, use the
``db_table`` Meta attribute. This has no effect on the API used to
query the database.

If you need to use a table name for a many-to-many relationship that differs
from the default generated name, use the ``db_table`` parameter on the
``ManyToManyField``. This has no effect on the API for querying the database.

"""

from __future__ import unicode_literals

from django.db import models
from django.utils.encoding import python_2_unicode_compatible

class CustomIntegerField(models.IntegerField):
    pass

class SubCustomIntegerField(CustomIntegerField):
    pass

@python_2_unicode_compatible
class Author(models.Model):
    name = models.CharField(max_length=30)
    age = SubCustomIntegerField()

    def __str__(self):
        return '%s' % (self.name)

    class Meta:
        ordering = ('name',)

class Div2Lookup(models.SimpleLookup):
    lookup_type = 'div2'

    def get_rhs_op(self, qn, connection, rhs):
        return '%%%% 2 = %s' % rhs

class Div3Lookup(models.SimpleLookup):
    lookup_type = 'div3'
    supports_nesting = True

    def get_rhs_op(self, qn, connection, rhs):
        return '%%%% 3 = %s' % rhs

    def as_nested_sql(self, qn, connection):
        lhs, value = self.process_lhs(qn, connection)
        return '%s %%%% 3' % lhs, value

    def get_lookup(self, lookups):
        return self.lhs.field.get_lookup(lookups)

    @property
    def output_type(self):
        return self.lhs.output_type

Author._meta.get_field('age').register_lookup(Div2Lookup)
Author._meta.get_field('age').register_lookup(Div3Lookup)

class NotEqual(models.SimpleLookup):
    lookup_type = 'ne'

    def as_sql(self, qn, connection):
        rhs, lhs, params = self.get_lhs_rhs(qn, connection)
        return '%s != %s' % (lhs, rhs), params

class FakeNotEqual(models.SimpleLookup):
    lookup_type = 'ne'

    def as_sql(self, qn, connection):
        rhs, lhs, params = self.get_lhs_rhs(qn, connection)
        return '%s = %s' % (lhs, rhs), params
