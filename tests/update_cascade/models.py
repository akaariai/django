from django.db import models


class ModelA(models.Model):
    a_field = models.CharField(max_length=20, unique=True)


class ModelB(models.Model):
    fk = models.ForeignKey(ModelA, to_field='a_field', on_update=models.CASCADE)


class Tree(models.Model):
    parent = models.ForeignKey('self', null=True, to_field='name', on_update=models.CASCADE)
    name = models.CharField(max_length=20, unique=True)


class RecursiveRef1(models.Model):
    name = models.CharField(max_length=20, unique=True)
    rev_fk = models.ForeignKey(
        'RecursiveRef2', unique=True, to_field='fk', null=True, aux_field='name',
        on_update=models.CASCADE
    )


class RecursiveRef2(models.Model):
    fk = models.ForeignKey(RecursiveRef1, unique=True, to_field='name',
                           on_update=models.CASCADE)


class Country(models.Model):
    name = models.CharField(max_length=20, unique=True)

class City(models.Model):
    country = models.ForeignKey(Country, to_field='name', on_update=models.CASCADE)
    name = models.CharField(max_length=20)
    country_city_uq = models.CompositeField(country, name, unique=True)

class Street(models.Model):
    city = models.ForeignKey(City, to_field='country_city_uq', on_update=models.CASCADE)
    name = models.CharField(max_length=20)
    country_city_street_uq = models.CompositeField(city, name, unique=True)
