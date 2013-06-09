from __future__ import unicode_literals

from django.core.cache.utils import make_template_fragment_key
from django.template import Library, TemplateSyntaxError, VariableDoesNotExist
from django.template.generic import TemplateTag, Grammar
from django.core.cache import cache

register = Library()

@register.tag
class CacheNode(TemplateTag):
    """
    This will cache the contents of a template fragment for a given amount
    of time.

    Usage::

        {% load cache %}
        {% cache [expire_time] [fragment_name] %}
            .. some expensive processing ..
        {% endcache %}

    This tag also supports varying by a list of arguments::

        {% load cache %}
        {% cache [expire_time] [fragment_name] [var1] [var2] .. %}
            .. some expensive processing ..
        {% endcache %}

    Each unique set of arguments will result in a unique cache entry.
    """
    grammar = Grammar('cache endcache')

    def __init__(self, parser, parse_result):
        tokens = parse_result.arguments
        if len(tokens) < 2:
            raise TemplateSyntaxError("'%r' tag requires at least 2 arguments." % parse_result.tagname)
        self.expire_time_var = parser.compile_filter(tokens[0])
        self.fragment_name = tokens[1] # fragment_name can't be a variable.
        self.vary_on = [parser.compile_filter(token) for token in tokens[2:]]

    def render(self, context):
        try:
            expire_time = self.expire_time_var.resolve(context)
        except VariableDoesNotExist:
            raise TemplateSyntaxError('"cache" tag got an unknown variable: %r' % self.expire_time_var.var)
        try:
            expire_time = int(expire_time)
        except (ValueError, TypeError):
            raise TemplateSyntaxError('"cache" tag got a non-integer timeout value: %r' % expire_time)
        vary_on = [var.resolve(context) for var in self.vary_on]
        cache_key = make_template_fragment_key(self.fragment_name, vary_on)
        value = cache.get(cache_key)
        if value is None:
            value = self.nodelist.render(context)
            cache.set(cache_key, value, expire_time)
        return value
