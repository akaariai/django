try:
    from urllib.parse import urljoin
except ImportError:     # Python 2
    from urlparse import urljoin

from django import template
from django.template.base import Node
from django.template.generic import TemplateTag, Grammar
from django.utils.encoding import iri_to_uri

register = template.Library()


class PrefixNode(TemplateTag):
    name = None
    grammar = None

    def __repr__(self):
        return "<PrefixNode for %r>" % self.name

    def __init__(self, parser, parse_result):
        """
        Class method to parse prefix node and return a Node.
        """
        tokens = parse_result.arguments.split()
        if len(tokens) > 0 and tokens[0] != 'as':
            raise template.TemplateSyntaxError(
                "First argument in '%s' must be 'as'" % parse_result.tagname)
        if len(tokens) > 0:
            self.varname = tokens[1]
        else:
            self.varname = None

        if self.name is None:
            raise template.TemplateSyntaxError(
                "Prefix nodes must be given a name to return.")

    @classmethod
    def handle_simple(cls, name):
        try:
            from django.conf import settings
        except ImportError:
            prefix = ''
        else:
            prefix = iri_to_uri(getattr(settings, name, ''))
        return prefix

    def render(self, context):
        prefix = self.handle_simple(self.name)
        if self.varname is None:
            return prefix
        context[self.varname] = prefix
        return ''


@register.tag
class StaticPrefixNode(PrefixNode):
    """
    Populates a template variable with the static prefix,
    ``settings.STATIC_URL``.

    Usage::

        {% get_static_prefix [as varname] %}

    Examples::

        {% get_static_prefix %}
        {% get_static_prefix as static_prefix %}

    """
    # token.split_contents() isn't useful here because tags using this method don't accept variable as arguments
    grammar = Grammar('get_static_prefix', _split_contents=False)
    name = 'STATIC_URL'


@register.tag
class MediaPrefixNode(PrefixNode):
    """
    Populates a template variable with the media prefix,
    ``settings.MEDIA_URL``.

    Usage::

        {% get_media_prefix [as varname] %}

    Examples::

        {% get_media_prefix %}
        {% get_media_prefix as media_prefix %}

    """
    grammar = Grammar('get_media_prefix', _split_contents=False)
    name = 'MEDIA_URL'


@register.tag
class StaticNode(TemplateTag):
    """
    Joins the given path with the STATIC_URL setting.

    Usage::

        {% static path [as varname] %}

    Examples::

        {% static "myapp/css/base.css" %}
        {% static variable_with_path %}
        {% static "myapp/css/base.css" as admin_base_css %}
        {% static variable_with_path as varname %}

    """
    grammar = Grammar('static')

    def __init__(self, parser, parse_result):
        """
        Class method to parse prefix node and return a Node.
        """
        bits = parse_result.arguments
        if len(bits) < 1:
            raise template.TemplateSyntaxError(
                "'%s' takes at least one argument (path to file)" % parse_result.tagname)

        self.path = parser.compile_filter(bits[0])

        if len(bits) >= 2 and bits[1] == 'as':
            self.varname = bits[2]
        else:
            self.varname = None

    def render(self, context):
        url = self.url(context)
        if self.varname is None:
            return url
        context[self.varname] = url
        return ''

    def url(self, context):
        path = self.path.resolve(context)
        return self.handle_simple(path)

    @classmethod
    def handle_simple(cls, path):
        return urljoin(PrefixNode.handle_simple("STATIC_URL"), path)


def static(path):
    return StaticNode.handle_simple(path)
