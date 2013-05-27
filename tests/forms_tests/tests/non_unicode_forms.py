# -*- coding: utf-8 -*-
# Note: Intentionally no from __future__ import unicode_literals
from django import forms

class TestForm(forms.Form):
    a_field = forms.IntegerField(label='fää')
