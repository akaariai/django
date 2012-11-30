from django.db import models
from django.db.models.base import ModelState

class UpdatablePKState(ModelState):
    old_pk = None

    def set_state(self, db, adding, obj, updated_fields=None, loaded_fields=None):
        self.db = db
        self.adding = adding
        self.old_pk = obj.pk

    def reset(self):
        self.db = None
        self.adding = True
        self.old_pk = None

class UpdatablePK(object):
    _state_cls = UpdatablePKState

    def _get_update_values(self, non_pks, pk_val, raw):
        values = super(UpdatablePK, self)._get_update_values(non_pks, pk_val, raw)
        if self._state.old_pk != pk_val:
            values.append((self._meta.pk, None, self._meta.pk.pre_save(self, False)))
        return values

    def _check_exists(self, base_qs, pk_val):
        return super(UpdatablePK, self)._check_exists(base_qs, self._state.old_pk or pk_val)

    def _do_update(self, base_qs, using, pk_val, values):
        return super(UpdatablePK, self)._do_update(
            base_qs, using, self._state.old_pk or pk_val, values)

class UpdatablePKModel(UpdatablePK, models.Model):
    code = models.CharField(max_length=20, primary_key=True)
    value = models.TextField()

class SingleFieldPK(UpdatablePK, models.Model):
    code = models.CharField(max_length=20, primary_key=True)

class ChangeTrackingState(ModelState):
    old_values = None

    def set_state(self, db, adding, obj, updated_fields=None, loaded_fields=None):
        self.db = db
        self.adding = adding
        if not updated_fields and not loaded_fields:
            loaded_fields = [f.attname for f in obj._meta.fields]
        if updated_fields:
            if self.old_values is not None:
                self.old_values.update((attname, getattr(obj, attname))
                                       for attname in updated_fields)
            else:
                self.old_values = ((attname, getattr(obj, attname))
                                       for attname in updated_fields)
        else:
            self.old_values = dict((attname, getattr(obj, attname))
                                   for attname in loaded_fields)

    def set_loaded_from_db(self, attname, value):
        self.old_values[attname] = value

    def reset(self):
        self.db = None
        self.adding = True
        self.old_values = None

class StateTracking(object):
    _state_cls = ChangeTrackingState

    def _get_update_values(self, non_pks, pk_val, raw):
        if self._state.old_values:
            for f in non_pks[:]:
                if getattr(self, f.attname) == self._state.old_values[f.attname]:
                    non_pks.remove(f)
        return super(StateTracking, self)._get_update_values(non_pks, pk_val, raw)

    def _check_exists(self, base_qs, pk_val):
        if self._state.db and self._state.old_values is not None and base_qs.db == self._state.db:
            # We end up in this check because no values need to be updated. We don't
            # want to do the check in this case for performance reasons. Instead just
            # assumte the object is still there.
            return True
        return super(StateTracking, self)._check_exists(base_qs, pk_val)

class TrackStateModel(StateTracking, models.Model):
    f1 = models.TextField()
    f2 = models.TextField()
    f3 = models.TextField()
