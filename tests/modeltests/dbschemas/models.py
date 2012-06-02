from django.db import models

class SameName1(models.Model):
    txt = models.TextField(null=True)

    class Meta:
        db_table = 'sn'

class SameName2(models.Model):
    fk = models.ForeignKey(SameName1)

    class Meta:
        db_table = 'sn'
        db_schema = 'schema1'

class SameName3(models.Model):
    fk = models.ForeignKey(SameName1)

    class Meta:
        db_table = 'sn'
        db_schema = 'schema2'

class M2MTable(models.Model):
    m2m = models.ManyToManyField(SameName1)

    class Meta:
        db_schema = 'schema1'

class M2MTable2(models.Model):
    m2m = models.ManyToManyField(SameName2)#, db_schema='schema3')

    class Meta:
        db_schema = 'schema2'

class PrefixCollision(models.Model):
    """
    On backends faking schemas by prefixing the table names this and the
    following model must have different qnames. The models are abstract,
    as testing connection.qname is enough. The models are tested with
    connection-level schema "foo".
    """
    class Meta:
        db_table = 'bar'
        abstract = True

class PrefixCollision2(models.Model):

    class Meta:
        db_table = 'foo_bar'
        abstract = True
