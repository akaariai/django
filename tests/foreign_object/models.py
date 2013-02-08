import datetime

from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import get_language

class Country(models.Model):
    # Table Column Fields
    name = models.CharField(max_length=50)

    def __unicode__(self):
        return self.name


class Person(models.Model):
    # Table Column Fields
    name = models.CharField(max_length=128)
    person_country_id = models.IntegerField()

    # Relation Fields
    person_country = models.ForeignObject(Country,
        from_fields=['person_country_id'],
        to_fields=['id'])
    friends = models.ManyToManyField('self', through='Friendship', symmetrical=False)

    class Meta:
        ordering = ('name',)

    def __unicode__(self):
        return self.name

class Group(models.Model):
    # Table Column Fields
    name = models.CharField(max_length=128)
    group_country = models.ForeignKey(Country)
    members = models.ManyToManyField(Person, related_name='groups', through='Membership')

    class Meta:
        ordering = ('name',)

    def __unicode__(self):
        return self.name


class Membership(models.Model):
    # Table Column Fields
    membership_country = models.ForeignKey(Country)
    date_joined = models.DateTimeField(default=datetime.datetime.now)
    invite_reason = models.CharField(max_length=64, null=True)
    person_id = models.IntegerField()
    group_id = models.IntegerField()

    # Relation Fields
    person = models.ForeignObject(Person,
        from_fields=['membership_country', 'person_id'],
        to_fields=['person_country_id', 'id'])
    group = models.ForeignObject(Group,
        from_fields=['membership_country', 'group_id'],
        to_fields=['group_country', 'id'])

    class Meta:
        ordering = ('date_joined', 'invite_reason')

    def __unicode__(self):
        return "%s is a member of %s" % (self.person.name, self.group.name)


class Friendship(models.Model):
    # Table Column Fields
    from_friend_country = models.ForeignKey(Country, related_name="from_friend_country")
    from_friend_id = models.IntegerField()
    to_friend_country_id = models.IntegerField()
    to_friend_id = models.IntegerField()

    # Relation Fields
    from_friend = models.ForeignObject(Person,
        from_fields=['from_friend_country', 'from_friend_id'],
        to_fields=['person_country_id', 'id'],
        related_name='from_friend')

    to_friend_country = models.ForeignObject(Country,
        from_fields=['to_friend_country_id'],
        to_fields=['id'],
        related_name='to_friend_country')

    to_friend = models.ForeignObject(Person,
        from_fields=['to_friend_country_id', 'to_friend_id'],
        to_fields=['person_country_id', 'id'],
        related_name='to_friend')

class ActiveTranslationField(models.ForeignObject):
    requires_unique_target = False

    def get_extra_join_sql(self, connection, qn, lhs_alias, rhs_alias):
        return " AND %s.%s = %%s" % (qn(rhs_alias), qn("lang")), [get_language()]

    def get_extra_filter(self):
        return {'lang': get_language()}

@python_2_unicode_compatible
class Article(models.Model):
    pub_date = models.DateTimeField()
    active_translation = ActiveTranslationField(
        'ArticleTranslation',
        from_fields=['id'],
        to_fields=['article'],
        related_name='+',
        null=True)

    def __str__(self):
        try:
            return self.active_translation.title
        except ArticleTranslation.DoesNotExist:
            return '[No translation found]'

class ArticleTranslation(models.Model):
    article = models.ForeignKey(Article)
    lang = models.CharField(max_length='2')
    title = models.CharField(max_length=100)
    body = models.TextField()
    abstract = models.CharField(max_length=400, null=True)

    class Meta:
        unique_together = ('article', 'lang')
        ordering = ('active_translation__title',)
