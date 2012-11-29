from django.db import models
from django.db.models.base import ModelState

class UpdatablePKState(ModelState):
    old_pk = None

    def set_state(self, db, adding, obj, updated_fields=None):
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
