from django import template
from django.contrib.admin.models import LogEntry

register = template.Library()

@register.tag
class AdminLogNode(template.TemplateTag):
    """
    Populates a template variable with the admin log for the given criteria.

    Usage::

        {% get_admin_log [limit] as [varname] for_user [context_var_containing_user_obj] %}

    Examples::

        {% get_admin_log 10 as admin_log for_user 23 %}
        {% get_admin_log 10 as admin_log for_user user %}
        {% get_admin_log 10 as admin_log %}

    Note that ``context_var_containing_user_obj`` can be a hard-coded integer
    (user ID) or the name of a template context variable containing the user
    object whose ID you want.
    """
    grammar = template.Grammar('get_admin_log')

    def __init__(self, parser, parse_result):
        bits = parse_result.arguments

        if len(bits) < 3:
            raise template.TemplateSyntaxError(
                "'get_admin_log' statements require two arguments")
        if not bits[0].isdigit():
            raise template.TemplateSyntaxError(
                "First argument to 'get_admin_log' must be an integer")
        if bits[1] != 'as':
            raise template.TemplateSyntaxError(
                "Second argument to 'get_admin_log' must be 'as'")
        if len(bits) > 3:
            if bits[3] != 'for_user':
                raise template.TemplateSyntaxError(
                    "Fourth argument to 'get_admin_log' must be 'for_user'")

        self.limit, self.varname, self.user = bits[0], bits[2], (bits[4] if len(bits) > 4 else None)

    def __repr__(self):
        return "<GetAdminLog Node>"

    def render(self, context):
        if self.user is None:
            context[self.varname] = LogEntry.objects.all().select_related('content_type', 'user')[:self.limit]
        else:
            user_id = self.user
            if not user_id.isdigit():
                user_id = context[self.user].pk
            context[self.varname] = LogEntry.objects.filter(user__pk__exact=user_id).select_related('content_type', 'user')[:int(self.limit)]
        return ''
