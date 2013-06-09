from django.template import TemplateTag, Grammar
from django.template import TemplateSyntaxError, Library
from django.utils import formats
from django.utils.encoding import force_text

register = Library()

@register.filter(is_safe=False)
def localize(value):
    """
    Forces a value to be rendered as a localized value,
    regardless of the value of ``settings.USE_L10N``.
    """
    return force_text(formats.localize(value, use_l10n=True))

@register.filter(is_safe=False)
def unlocalize(value):
    """
    Forces a value to be rendered as a non-localized value,
    regardless of the value of ``settings.USE_L10N``.
    """
    return force_text(value)

@register.tag
class LocalizeNode(TemplateTag):
    """
    Forces or prevents localization of values, regardless of the value of
    `settings.USE_L10N`.

    Sample usage::

        {% localize off %}
            var pi = {{ 3.1415 }};
        {% endlocalize %}

    """
    grammar = Grammar('localize endlocalize')

    def __init__(self, parser, parse_result):
        self.use_l10n = None
        bits = parse_result.arguments
        if len(bits) == 0:
            self.use_l10n = True
        elif len(bits) > 1 or bits[0] not in ('on', 'off'):
            raise TemplateSyntaxError("%r argument should be 'on' or 'off'" % self.parse_result.tagname)
        else:
            self.use_l10n = bits[0] == 'on'

    def __repr__(self):
        return "<LocalizeNode>"

    def render(self, context):
        old_setting = context.use_l10n
        context.use_l10n = self.use_l10n
        output = self.nodelist.render(context)
        context.use_l10n = old_setting
        return output

