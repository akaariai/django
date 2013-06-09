from django import template
from django.templatetags.static import StaticNode
from django.contrib.staticfiles.storage import staticfiles_storage

register = template.Library()


@register.tag
class StaticFilesNode(StaticNode):
    """
    A template tag that returns the URL to a file
    using staticfiles' storage backend

    Usage::

        {% static path [as varname] %}

    Examples::

        {% static "myapp/css/base.css" %}
        {% static variable_with_path %}
        {% static "myapp/css/base.css" as admin_base_css %}
        {% static variable_with_path as varname %}

    """
    grammar = template.Grammar('static')

    def url(self, context):
        path = self.path.resolve(context)
        return staticfiles_storage.url(path)


def static(path):
    return staticfiles_storage.url(path)
