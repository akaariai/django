from django.db.models.fields.related import (ReverseSingleRelatedObjectDescriptor,
                                             ForeignObject)


class ReverseUniqueDescriptor(ReverseSingleRelatedObjectDescriptor):
    """
    The set of articletranslation should not set any local fields.
    """
    def __set__(self, instance, value):
        if instance is None:
            raise AttributeError("%s must be accessed via instance" % self.field.name)
        setattr(instance, self.cache_name, value)
        if value is not None and not self.field.rel.multiple:
            setattr(value, self.field.related.get_cache_name(), instance)

    def __get__(self, instance, *args, **kwargs):
        try:
            return super(ReverseUniqueDescriptor, self).__get__(instance, *args, **kwargs)
        except self.field.rel.to.DoesNotExist:
            setattr(instance, self.cache_name, None)
            return None

class ReverseUnique(ForeignObject):
    """
    This field will allow querying and fetching the currently active translation
    for Article from ArticleTranslation.
    """
    requires_unique_target = False

    def __init__(self, *args, **kwargs):
        self.filters = kwargs.pop('filters')
        self.related_field = kwargs.pop('related_field')
        kwargs['from_fields'] = []
        kwargs['to_fields'] = []
        kwargs['null'] = True
        kwargs['related_name'] = '+'
        super(ReverseUnique, self).__init__(*args, **kwargs)

    def resolve_related_fields(self):
        related_field = self.rel.to._meta.get_field_by_name(self.related_field)[0]
        self.to_fields = related_field.from_fields
        self.from_fields = related_field.to_fields
        return related_field.reverse_related_fields

    def get_extra_restriction(self, where_class, alias, related_alias):
        qs = self.rel.to.objects.filter(self.filters).query
        my_table = self.model._meta.db_table
        rel_table = self.rel.to._meta.db_table
        illegal_tables = set(qs.tables).difference(
            set([my_table, rel_table]))
        if illegal_tables:
            raise Exception("self.filters refers illegal tables: %s" % illegal_tables)
        where = qs.where
        where.relabel_aliases({my_table: related_alias, rel_table: alias})
        return where

    def get_extra_descriptor_filter(self, instance):
        return self.filters

    def get_path_info(self):
        ret = super(ReverseUnique, self).get_path_info()
        assert len(ret) == 1
        return [ret[0]._replace(direct=False)]

    def contribute_to_class(self, cls, name):
        super(ReverseUnique, self).contribute_to_class(cls, name)
        setattr(cls, self.name, ReverseUniqueDescriptor(self))
