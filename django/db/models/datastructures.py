class Col(object):
    is_aggregate = False
    convert_value = None

    def __init__(self, alias, field, output_type=None):
        self.alias, self.field, self.output_type = alias, field, output_type or field

    def as_sql(self, qn, connection):
        return "%s.%s" % (qn(self.alias), qn(self.field.column)), []

    def relabeled_clone(self, change_map):
        return self.__class__(change_map.get(self.alias, self.alias),
                              self.field, self.output_type)

    def get_lookup(self, lookup):
        return self.output_type.get_lookup(lookup)

    def get_cols(self):
        return [self]

    @property
    def alias_label(self):
        return self.field.column

    def remove_from_query(self, query):
        query.unref_alias(self.alias, cascade=True)


class Empty(object):
    pass

class RefCol(object):
    is_aggregate = False
    output_type = None
    allow_nulls = True
    convert_value = None

    def __init__(self, lookup):
        self.lookup = lookup

    def add_to_query(self, query, alias):
        self.col = query.get_ref(self.lookup, allow_nulls=self.allow_nulls)
        if self.output_type is None:
            self.output_type = self.col.output_type
        self.field = self.output_type
        self.alias_label = alias
        return self

    def remove_from_query(self, query):
        self.col.remove_from_query(query)

    def get_cols(self):
        return [] if self.is_aggregate else self.col.get_cols()

    def relabeled_clone(self, change_map):
        clone = Empty()
        clone.__class__ = self.__class__
        clone.__dict__ = self.__dict__.copy()
        clone.col = self.col.relabeled_clone(change_map)
        return clone

    def get_lookup(self, lookup):
        return self.output_type.get_lookup(lookup)

class MultiRefCol(object):
    is_aggregate = False
    output_type = None
    convert_value = None

    def __init__(self, lookups):
        self.lookups = lookups
        self.field = self

    def add_to_query(self, query, alias):
        self.cols = []
        for lookup in self.lookups:
            self.cols.append(query.get_ref(lookup))
        if self.output_type is None:
            # Wild guess..
            self.output_type = self.cols[0].output_type
        self.field = self.output_type
        self.alias_label = alias
        return self

    def remove_from_query(self, query):
        for col in self.cols:
            col.remove_from_query(query)

    def get_cols(self):
        if self.is_aggregate:
            return []
        else:
            ret = []
            for col in self.cols:
                ret.extend(col.get_cols())

    def relabeled_clone(self, change_map):
        clone = Empty()
        clone.__class__ = self.__class__
        clone.__dict__ = self.__dict__.copy()
        clone.cols = [col.relabeled_clone(change_map) for col in self.cols]
        return clone

    def get_lookup(self, lookup):
        return self.output_type.get_lookup(lookup)
