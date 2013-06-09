from django.template import Library
from django.template import defaulttags, TemplateTag, Grammar

register = Library()


@register.tag
class SsiNode(defaulttags.SsiNode):
    # Used for deprecation path during 1.3/1.4, will be removed in 2.0
    pass


@register.tag
class URLNode(defaulttags.URLNode):
    # Used for deprecation path during 1.3/1.4, will be removed in 2.0
    pass


@register.tag
class CycleNode(defaulttags.CycleNode):
    """
    This is the future version of `cycle` with auto-escaping.

    By default all strings are escaped.

    If you want to disable auto-escaping of variables you can use::

        {% autoescape off %}
            {% cycle var1 var2 var3 as somecycle %}
        {% autoescape %}

    Or if only some variables should be escaped, you can use::

        {% cycle var1 var2|safe var3|safe  as somecycle %}
    """
    escape = True


@register.tag
class FirstOfNode(defaulttags.FirstOfNode):
    """
    This is the future version of `firstof` with auto-escaping.

    This is equivalent to::

        {% if var1 %}
            {{ var1 }}
        {% elif var2 %}
            {{ var2 }}
        {% elif var3 %}
            {{ var3 }}
        {% endif %}

    If you want to disable auto-escaping of variables you can use::

        {% autoescape off %}
            {% firstof var1 var2 var3 "<strong>fallback value</strong>" %}
        {% autoescape %}

    Or if only some variables should be escaped, you can use::

        {% firstof var1 var2|safe var3 "<strong>fallback value</strong>"|safe %}

    """
    escape = True
