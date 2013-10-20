"""
Logic for handling update cascades.
"""
from django.db import IntegrityError

class UpdateProtectedError(IntegrityError):
    pass


def PROTECT(collector, field, sub_objs, using):
    raise UpdateProtectedError(
        "Cannot delete some instances of model '%s' because "
        "they are referenced through a protected foreign key: '%s.%s'" % (
            field.rel.to.__name__, sub_objs[0].__class__.__name__, field.name
        ),
        sub_objs
    )

class Collector(object):
    def __init__(self, using):
        self.using = using
        self.updates = []

    def collect(self, field, from_vals, to_val):
        """
        Adds an update for field from_val to to_val.

        The field should be a foreign key or subclass thereof.

        The from_vals parameter is anything that can be used in
        filter(field__in=from_vals).

        The to_val parameter is anything that works in qs.update(**to_val).
        """
        # This implementation handles cascades lazily. Any update adds three
        # things to self.updates:
        #     - A way to do the actual updates
        #       (any callable without arguments will do)
        #     - A way to ask if more cascades are needed
        #       (again, any callable will do, most commonly this is .exists()
        #        call or plain return False if there is no possibility for
        #        more cascades)
        #     - A callable for executing the cascade if needed above.
        #  These are executed in
        #      needs_cascade(); update(); if needed_cascade: cascade()
        #  order.
        model = field.model
        possible_cascades = self.collect_possible_cascades(field)
        qs = model._base_manager.using(self.using).filter(
            **{field.name + '__in': from_vals})
        update = self.build_update_impl(qs, to_val, possible_cascades)
        if not possible_cascades:
            cascade_impl = lambda x: None
        else:
            cascade_impl = self.build_cascade_impl(
                field, possible_cascades, to_val)
        self.updates.append((update, cascade_impl))

    def _fields_concrete_intersection(self, field, related_field):
        if not issubclass(field.model, related_field.rel.to):
            return set()
        related_concrete_fields = set(
            f.name for f in related_field.related_field.concrete_fields)
        concrete_fields = set(
            f.name for f in field.concrete_fields)
        intersection = related_concrete_fields.intersection(concrete_fields)
        if intersection:
            return dict(
                (to_field.name, from_field)
                for from_field, to_field in related_field.related_fields
                if to_field.name in intersection)
        else:
            return set()

    def collect_possible_cascades(self, field):
        opts = field.model._meta
        related = opts.get_all_related_objects(
            include_hidden=True, include_proxy_eq=True)
        cascades = []
        from django.db.models.deletion import DO_NOTHING
        for rel in related:
            rel_field = rel.field
            if rel_field.rel.on_update == DO_NOTHING:
                continue
            concrete_intersection = self._fields_concrete_intersection(
                field, rel_field)
            if not concrete_intersection:
                continue
            cascades.append((rel_field, concrete_intersection))
        return cascades

    def collect_field_update(self, field, from_vals, to_val):
        """
        Like collect, but field can be any field updated to new value.
        """
        cascades = self.collect_possible_cascades(field)
        for rel_field, concrete_fields in cascades:
            related_to_val = self.related_to_val(to_val, concrete_fields)
            self.collect(
                rel_field, from_vals=from_vals, to_val=related_to_val)

    def related_to_val(self, to_val, concrete_fields):
        related_to_val = {}
        for k, v in to_val.items():
            if k in concrete_fields:
                related_to_val[concrete_fields[k].name] = v
        return related_to_val

    def relabeled_new_from_vals(self, qs, possible_cascades):
        new_from_vals = self.new_from_vals(qs, possible_cascades)
        return self.relabel_vals(new_from_vals, possible_cascades)

    def new_from_vals(self, qs, possible_cascades):
        fnames = [f.related_field.name for f, _ in possible_cascades]
        return list(qs.values(*fnames).distinct())

    def relabel_vals(self, vals, possible_cascades):
        realiased_vals = []
        for d in vals:
            new_d = {}
            for f, _ in possible_cascades:
                new_d[f.name] = d[f.related_field.name]
            realiased_vals.append(new_d)
        return realiased_vals

    def build_update_impl(self, qs, to_val, possible_cascades):
        def execute():
            new_from_vals = self.relabeled_new_from_vals(qs, possible_cascades)
            if new_from_vals:
                qs.update(**to_val)
            return new_from_vals
        return execute

    def build_cascade_impl(self, field, possible_cascades, to_val):
        def execute(new_from_vals):
            if new_from_vals:
                for cascade, concrete_fields in possible_cascades:
                    cascade.rel.on_update.do_update(
                        self.using, cascade, concrete_fields, new_from_vals, to_val)
        return execute

    def cascade_model_update(self, instance, update_fields):
        if update_fields is not None and not update_fields:
            return
        possible_cascades = []
        if not update_fields:
            update_fields = [f.name for f in instance._meta.concrete_fields]
        for fname in update_fields:
            field = instance._meta.get_field(fname)
            possible_cascades.extend(self.collect_possible_cascades(field))
        if possible_cascades:
            changed_vals = self.changed_vals(instance, possible_cascades)
            for k, v in changed_vals.items():
                to_field = instance._meta.get_field(k)
                concrete_fields = to_field.concrete_fields
                to_val = dict([(f.name, getattr(instance, f.name)) for f in concrete_fields])
                self.collect_field_update(
                    instance._meta.get_field(k), [v], to_val)
        self.update()

    def changed_vals(self, instance, possible_cascades):
        from_vals = self.new_from_vals(
            instance._base_manager.filter(pk=instance.pk),
            possible_cascades)
        assert len(from_vals) < 2, 'At most one row for one instance should exists'
        if not from_vals:
            return []
        from_vals = from_vals[0]
        return dict([(k, v) for k, v in from_vals.items()
                     if getattr(instance, k) != v])

    def update(self):
        for update, cascade_impl in self.updates:
            new_from_vals = update()
            cascade_impl(new_from_vals)
