import operator

from django import template
from django.template.defaultfilters import stringfilter
from django.template.loader import get_template
from django.template.generic import TemplateTag, Grammar
from django.utils import six

register = template.Library()



@register.tag
class OneTag(TemplateTag):
    """
    A simple templatetag which does nothing actually.
    {% cb_one_tag %}
    """
    grammar = Grammar('cb_one_tag')

@register.tag
class TwoTags(TemplateTag):
    """
    A templatetag which just renders the containing nodes.
    {% cb_two_tags %} ... {% end_cb_two_tags %}
    """
    grammar = Grammar('cb_two_tags end_cb_two_tags')

@register.tag
class ToUpper(TemplateTag):
    """
    A template tags which converts the inner noders to uppercase
    after rendering.
    {% cb_to_upper %} ... {% end_cb_to_upper %}
    """
    grammar = Grammar('cb_to_upper end_cb_to_upper')

    def render(self, context):
        return self.nodelist.render(context).upper()

@register.tag
class WithMiddleTag(TemplateTag):
    """
    A template tags pair which has a middle tag.
    {% cb_with_middle %} ... {% middle %} ... {% end_cb_with_middle %}
    """
    grammar = Grammar('cb_with_middle middle end_cb_with_middle')

@register.tag
class RenderSecondNode(TemplateTag):
    """
    A template tags which converts the inner noders to uppercase
    after rendering.
    {% cb_render_second %} ... {% middle %} ... {% end_cb_render_second %}
    """
    grammar = Grammar('cb_render_second middle end_cb_render_second')

    def render(self, context):
        return self.parse_result.parts[1].nodelist.render(context)

@register.tag
class RenderSecondNode2(TemplateTag):
    """
    Another approach.
    {% cb_render_second2 %} ... {% middle %} ... {% end_cb_render_second2 %}
    """
    grammar = Grammar('cb_render_second2 middle end_cb_render_second2')

    def __init__(self, parser, parse_result):
        self.second_nodelist = parse_result.parts[1].nodelist

    def render(self, context):
        return self.second_nodelist.render(context)

@register.tag
class OptionalMiddle(TemplateTag):
    """
    The middle tag optional. Just renders everything.
    {% cb_optional_middle %} ... {% middle %} ... {% end_cb_optional_middle %}
    """
    grammar = Grammar('cb_optional_middle middle? end_cb_optional_middle')

@register.tag
class RepeatingMiddle(TemplateTag):
    """
    The middle tag repeatable 0..n times.
    """
    grammar = Grammar('cb_repeating_middle middle* end_cb_repeating_middle')

@register.tag
class OneOrMoreMidleMiddle(TemplateTag):
    """
    The middle tag repeatable 1..n times.
    """
    grammar = Grammar('cb_one_or_more_middle middle+ end_cb_one_or_more_middle')

@register.tag
class ReverseBlocks(TemplateTag):
    """
    Reverse blocks: render the last parst first and the first part last.
    {% cb_reverse_blocks %} ... {% next %} ... {% next %} ... {% end_cb_reverse_blocks %}
    """
    grammar = Grammar('cb_reverse_blocks next* end_cb_reverse_blocks')

    def render(self, context):
        return ''.join(p.nodelist.render(context) for p in self.parse_result.parts[::-1])

@register.tag
class ComplexGrammar1(TemplateTag):
    """
    Some complex grammar rule.
    """
    grammar = Grammar('cb_complex1 A* B C? D+ E? end_cb_complex1')

@register.tag
class PrintParam1(TemplateTag):
    """
    Print tag parameters.
    {% cb_print_params "param1" "param2" ... %}
    """
    grammar = Grammar('cb_print_params')

    def render(self, context):
        return ' '.join(self.parse_result.arguments)

@register.tag
class PrintParam2(TemplateTag):
    """
    Print tag parameters.
    {% cb_print_params2 "param1" "param2" ... %} {% end_cb_print_params2 "end1" "end2" ... %}
    """
    grammar = Grammar('cb_print_params2 end_cb_print_params2')

    def render(self, context):
        return ' '.join(self.parse_result.parts[0].arguments) + \
               self.parse_result.parts[0].nodelist.render(context) + \
               ' '.join(self.parse_result.parts[-1].arguments)


@register.tag
class PrintAndResolveParams(TemplateTag):
    """
    Print each parameters after resolving in in the context.
    {% cb_print_and_resolv "param1" "param2" ... %}
    """
    grammar = Grammar('cb_print_and_resolv')

    def __init__(self, parser, parse_result):
        self.variables = [
            parser.compile_filter(a) for a in parse_result.arguments]

    def render(self, context):
        return ' '.join(map(str, (v.resolve(context) for v in self.variables)))
