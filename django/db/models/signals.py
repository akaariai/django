from django.dispatch import Signal

class_prepared = Signal(providing_args=["class"])

model_changed = Signal(providing_args=["using"])

class ModelModificationSignal(Signal):
    def send(self, sender, *args, **kwargs):
        model_changed.send(sender)
        super(ModelModificationSignal, self).send(sender, *args, **kwargs)

    def send_robust(self, sender, *args, **kwargs):
        model_changed.send(sender)
        super(ModelModificationSignal, self).send_robust(sender, *args, **kwargs)


pre_init = Signal(providing_args=["instance", "args", "kwargs"])
post_init = Signal(providing_args=["instance"])

pre_save = ModelModificationSignal(
    providing_args=["instance", "raw", "using", "update_fields"])
post_save = ModelModificationSignal(
    providing_args=["instance", "raw", "created", "using", "update_fields"])

pre_delete = ModelModificationSignal(providing_args=["instance", "using"])
post_delete = ModelModificationSignal(providing_args=["instance", "using"])

post_syncdb = Signal(providing_args=["class", "app", "created_models", "verbosity", "interactive"])

m2m_changed = ModelModificationSignal(
    providing_args=["action", "instance", "reverse", "model", "pk_set", "using"])
