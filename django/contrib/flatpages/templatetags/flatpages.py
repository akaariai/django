from django import template
from django.conf import settings
from django.contrib.flatpages.models import FlatPage
from django.contrib.sites.models import get_current_site
from django.template.generic import TemplateTag, Grammar


register = template.Library()

@register.tag
class FlatpageNode(TemplateTag):
    """
    Retrieves all flatpage objects available for the current site and
    visible to the specific user (or visible to all users if no user is
    specified). Populates the template context with them in a variable
    whose name is defined by the ``as`` clause.

    An optional ``for`` clause can be used to control the user whose
    permissions are to be used in determining which flatpages are visible.

    An optional argument, ``starts_with``, can be applied to limit the
    returned flatpages to those beginning with a particular base URL.
    This argument can be passed as a variable or a string, as it resolves
    from the template context.

    Syntax::

        {% get_flatpages ['url_starts_with'] [for user] as context_name %}

    Example usage::

        {% get_flatpages as flatpages %}
        {% get_flatpages for someuser as flatpages %}
        {% get_flatpages '/about/' as about_pages %}
        {% get_flatpages prefix as about_pages %}
        {% get_flatpages '/about/' for someuser as about_pages %}
    """
    grammar = Grammar('get_flatpages')

    def __init__(self, parser, parse_result):
        bits = parse_result.arguments
        tagname = parse_result.tagname
        syntax_message = ("%(tag_name)s expects a syntax of %(tag_name)s "
                           "['url_starts_with'] [for user] as context_name" %
                           dict(tag_name=tagname))
        # Must have at 2-5 bits in the tag
        if not (len(bits) >= 2 and len(bits) <= 5):
            raise template.TemplateSyntaxError(syntax_message)

        # If there's an even number of bits, there's no prefix
        if len(bits) % 2 == 0:
            prefix = None
        else:
            prefix = bits[0]

        # The very last bit must be the context name
        if bits[-2] != 'as':
            raise template.TemplateSyntaxError(syntax_message)
        self.context_name = bits[-1]

        # If there are 4 or 5 bits, there is a user defined
        if len(bits) >= 4:
            if bits[-4] != 'for':
                raise template.TemplateSyntaxError(syntax_message)
            user = bits[-3]
        else:
            user = None

        self.starts_with = template.Variable(prefix) if prefix else None
        self.user = template.Variable(user) if user else None

    def render(self, context):
        if 'request' in context:
            site_pk = get_current_site(context['request']).pk
        else:
            site_pk = settings.SITE_ID
        flatpages = FlatPage.objects.filter(sites__id=site_pk)
        # If a prefix was specified, add a filter
        if self.starts_with:
            flatpages = flatpages.filter(
                url__startswith=self.starts_with.resolve(context))

        # If the provided user is not authenticated, or no user
        # was provided, filter the list to only public flatpages.
        if self.user:
            user = self.user.resolve(context)
            if not user.is_authenticated():
                flatpages = flatpages.filter(registration_required=False)
        else:
            flatpages = flatpages.filter(registration_required=False)

        context[self.context_name] = flatpages
        return ''


