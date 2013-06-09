from __future__ import absolute_import, unicode_literals

from django import template
from django.utils import six
from django.utils.unittest import TestCase

from .templatetags import custom


class CustomFilterTests(TestCase):
    def test_filter(self):
        t = template.Template("{% load custom %}{{ string|trim:5 }}")
        self.assertEqual(
            t.render(template.Context({"string": "abcdefghijklmnopqrstuvwxyz"})),
            "abcde"
        )


class CustomTagTests(TestCase):
    def verify_tag(self, tag, name):
        self.assertEqual(tag.__name__, name)
        self.assertEqual(tag.__doc__, 'Expected %s __doc__' % name)
        self.assertEqual(tag.__dict__['anything'], 'Expected %s __dict__' % name)

    def test_simple_tags(self):
        c = template.Context({'value': 42})

        t = template.Template('{% load custom %}{% no_params %}')
        self.assertEqual(t.render(c), 'no_params - Expected result')

        t = template.Template('{% load custom %}{% one_param 37 %}')
        self.assertEqual(t.render(c), 'one_param - Expected result: 37')

        t = template.Template('{% load custom %}{% explicit_no_context 37 %}')
        self.assertEqual(t.render(c), 'explicit_no_context - Expected result: 37')

        t = template.Template('{% load custom %}{% no_params_with_context %}')
        self.assertEqual(t.render(c), 'no_params_with_context - Expected result (context value: 42)')

        t = template.Template('{% load custom %}{% params_and_context 37 %}')
        self.assertEqual(t.render(c), 'params_and_context - Expected result (context value: 42): 37')

        t = template.Template('{% load custom %}{% simple_two_params 37 42 %}')
        self.assertEqual(t.render(c), 'simple_two_params - Expected result: 37, 42')

        t = template.Template('{% load custom %}{% simple_one_default 37 %}')
        self.assertEqual(t.render(c), 'simple_one_default - Expected result: 37, hi')

        t = template.Template('{% load custom %}{% simple_one_default 37 two="hello" %}')
        self.assertEqual(t.render(c), 'simple_one_default - Expected result: 37, hello')

        t = template.Template('{% load custom %}{% simple_one_default one=99 two="hello" %}')
        self.assertEqual(t.render(c), 'simple_one_default - Expected result: 99, hello')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'simple_one_default' received unexpected keyword argument 'three'",
            template.Template, '{% load custom %}{% simple_one_default 99 two="hello" three="foo" %}')

        t = template.Template('{% load custom %}{% simple_one_default 37 42 %}')
        self.assertEqual(t.render(c), 'simple_one_default - Expected result: 37, 42')

        t = template.Template('{% load custom %}{% simple_unlimited_args 37 %}')
        self.assertEqual(t.render(c), 'simple_unlimited_args - Expected result: 37, hi')

        t = template.Template('{% load custom %}{% simple_unlimited_args 37 42 56 89 %}')
        self.assertEqual(t.render(c), 'simple_unlimited_args - Expected result: 37, 42, 56, 89')

        t = template.Template('{% load custom %}{% simple_only_unlimited_args %}')
        self.assertEqual(t.render(c), 'simple_only_unlimited_args - Expected result: ')

        t = template.Template('{% load custom %}{% simple_only_unlimited_args 37 42 56 89 %}')
        self.assertEqual(t.render(c), 'simple_only_unlimited_args - Expected result: 37, 42, 56, 89')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'simple_two_params' received too many positional arguments",
            template.Template, '{% load custom %}{% simple_two_params 37 42 56 %}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'simple_one_default' received too many positional arguments",
            template.Template, '{% load custom %}{% simple_one_default 37 42 56 %}')

        t = template.Template('{% load custom %}{% simple_unlimited_args_kwargs 37 40|add:2 56 eggs="scrambled" four=1|add:3 %}')
        self.assertEqual(t.render(c), 'simple_unlimited_args_kwargs - Expected result: 37, 42, 56 / eggs=scrambled, four=4')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'simple_unlimited_args_kwargs' received some positional argument\(s\) after some keyword argument\(s\)",
            template.Template, '{% load custom %}{% simple_unlimited_args_kwargs 37 40|add:2 eggs="scrambled" 56 four=1|add:3 %}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'simple_unlimited_args_kwargs' received multiple values for keyword argument 'eggs'",
            template.Template, '{% load custom %}{% simple_unlimited_args_kwargs 37 eggs="scrambled" eggs="scrambled" %}')

    def test_simple_tag_registration(self):
        # Test that the decorators preserve the decorated function's docstring, name and attributes.
        self.verify_tag(custom.no_params, 'no_params')
        self.verify_tag(custom.one_param, 'one_param')
        self.verify_tag(custom.explicit_no_context, 'explicit_no_context')
        self.verify_tag(custom.no_params_with_context, 'no_params_with_context')
        self.verify_tag(custom.params_and_context, 'params_and_context')
        self.verify_tag(custom.simple_unlimited_args_kwargs, 'simple_unlimited_args_kwargs')
        self.verify_tag(custom.simple_tag_without_context_parameter, 'simple_tag_without_context_parameter')

    def test_simple_tag_missing_context(self):
        # The 'context' parameter must be present when takes_context is True
        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'simple_tag_without_context_parameter' is decorated with takes_context=True so it must have a first argument of 'context'",
            template.Template, '{% load custom %}{% simple_tag_without_context_parameter 123 %}')

    def test_inclusion_tags(self):
        c = template.Context({'value': 42})

        t = template.Template('{% load custom %}{% inclusion_no_params %}')
        self.assertEqual(t.render(c), 'inclusion_no_params - Expected result\n')

        t = template.Template('{% load custom %}{% inclusion_one_param 37 %}')
        self.assertEqual(t.render(c), 'inclusion_one_param - Expected result: 37\n')

        t = template.Template('{% load custom %}{% inclusion_explicit_no_context 37 %}')
        self.assertEqual(t.render(c), 'inclusion_explicit_no_context - Expected result: 37\n')

        t = template.Template('{% load custom %}{% inclusion_no_params_with_context %}')
        self.assertEqual(t.render(c), 'inclusion_no_params_with_context - Expected result (context value: 42)\n')

        t = template.Template('{% load custom %}{% inclusion_params_and_context 37 %}')
        self.assertEqual(t.render(c), 'inclusion_params_and_context - Expected result (context value: 42): 37\n')

        t = template.Template('{% load custom %}{% inclusion_two_params 37 42 %}')
        self.assertEqual(t.render(c), 'inclusion_two_params - Expected result: 37, 42\n')

        t = template.Template('{% load custom %}{% inclusion_one_default 37 %}')
        self.assertEqual(t.render(c), 'inclusion_one_default - Expected result: 37, hi\n')

        t = template.Template('{% load custom %}{% inclusion_one_default 37 two="hello" %}')
        self.assertEqual(t.render(c), 'inclusion_one_default - Expected result: 37, hello\n')

        t = template.Template('{% load custom %}{% inclusion_one_default one=99 two="hello" %}')
        self.assertEqual(t.render(c), 'inclusion_one_default - Expected result: 99, hello\n')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'inclusion_one_default' received unexpected keyword argument 'three'",
            template.Template, '{% load custom %}{% inclusion_one_default 99 two="hello" three="foo" %}')

        t = template.Template('{% load custom %}{% inclusion_one_default 37 42 %}')
        self.assertEqual(t.render(c), 'inclusion_one_default - Expected result: 37, 42\n')

        t = template.Template('{% load custom %}{% inclusion_unlimited_args 37 %}')
        self.assertEqual(t.render(c), 'inclusion_unlimited_args - Expected result: 37, hi\n')

        t = template.Template('{% load custom %}{% inclusion_unlimited_args 37 42 56 89 %}')
        self.assertEqual(t.render(c), 'inclusion_unlimited_args - Expected result: 37, 42, 56, 89\n')

        t = template.Template('{% load custom %}{% inclusion_only_unlimited_args %}')
        self.assertEqual(t.render(c), 'inclusion_only_unlimited_args - Expected result: \n')

        t = template.Template('{% load custom %}{% inclusion_only_unlimited_args 37 42 56 89 %}')
        self.assertEqual(t.render(c), 'inclusion_only_unlimited_args - Expected result: 37, 42, 56, 89\n')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'inclusion_two_params' received too many positional arguments",
            template.Template, '{% load custom %}{% inclusion_two_params 37 42 56 %}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'inclusion_one_default' received too many positional arguments",
            template.Template, '{% load custom %}{% inclusion_one_default 37 42 56 %}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'inclusion_one_default' did not receive value\(s\) for the argument\(s\): 'one'",
            template.Template, '{% load custom %}{% inclusion_one_default %}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'inclusion_unlimited_args' did not receive value\(s\) for the argument\(s\): 'one'",
            template.Template, '{% load custom %}{% inclusion_unlimited_args %}')

        t = template.Template('{% load custom %}{% inclusion_unlimited_args_kwargs 37 40|add:2 56 eggs="scrambled" four=1|add:3 %}')
        self.assertEqual(t.render(c), 'inclusion_unlimited_args_kwargs - Expected result: 37, 42, 56 / eggs=scrambled, four=4\n')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'inclusion_unlimited_args_kwargs' received some positional argument\(s\) after some keyword argument\(s\)",
            template.Template, '{% load custom %}{% inclusion_unlimited_args_kwargs 37 40|add:2 eggs="scrambled" 56 four=1|add:3 %}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'inclusion_unlimited_args_kwargs' received multiple values for keyword argument 'eggs'",
            template.Template, '{% load custom %}{% inclusion_unlimited_args_kwargs 37 eggs="scrambled" eggs="scrambled" %}')

    def test_include_tag_missing_context(self):
        # The 'context' parameter must be present when takes_context is True
        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'inclusion_tag_without_context_parameter' is decorated with takes_context=True so it must have a first argument of 'context'",
            template.Template, '{% load custom %}{% inclusion_tag_without_context_parameter 123 %}')

    def test_inclusion_tags_from_template(self):
        c = template.Context({'value': 42})

        t = template.Template('{% load custom %}{% inclusion_no_params_from_template %}')
        self.assertEqual(t.render(c), 'inclusion_no_params_from_template - Expected result\n')

        t = template.Template('{% load custom %}{% inclusion_one_param_from_template 37 %}')
        self.assertEqual(t.render(c), 'inclusion_one_param_from_template - Expected result: 37\n')

        t = template.Template('{% load custom %}{% inclusion_explicit_no_context_from_template 37 %}')
        self.assertEqual(t.render(c), 'inclusion_explicit_no_context_from_template - Expected result: 37\n')

        t = template.Template('{% load custom %}{% inclusion_no_params_with_context_from_template %}')
        self.assertEqual(t.render(c), 'inclusion_no_params_with_context_from_template - Expected result (context value: 42)\n')

        t = template.Template('{% load custom %}{% inclusion_params_and_context_from_template 37 %}')
        self.assertEqual(t.render(c), 'inclusion_params_and_context_from_template - Expected result (context value: 42): 37\n')

        t = template.Template('{% load custom %}{% inclusion_two_params_from_template 37 42 %}')
        self.assertEqual(t.render(c), 'inclusion_two_params_from_template - Expected result: 37, 42\n')

        t = template.Template('{% load custom %}{% inclusion_one_default_from_template 37 %}')
        self.assertEqual(t.render(c), 'inclusion_one_default_from_template - Expected result: 37, hi\n')

        t = template.Template('{% load custom %}{% inclusion_one_default_from_template 37 42 %}')
        self.assertEqual(t.render(c), 'inclusion_one_default_from_template - Expected result: 37, 42\n')

        t = template.Template('{% load custom %}{% inclusion_unlimited_args_from_template 37 %}')
        self.assertEqual(t.render(c), 'inclusion_unlimited_args_from_template - Expected result: 37, hi\n')

        t = template.Template('{% load custom %}{% inclusion_unlimited_args_from_template 37 42 56 89 %}')
        self.assertEqual(t.render(c), 'inclusion_unlimited_args_from_template - Expected result: 37, 42, 56, 89\n')

        t = template.Template('{% load custom %}{% inclusion_only_unlimited_args_from_template %}')
        self.assertEqual(t.render(c), 'inclusion_only_unlimited_args_from_template - Expected result: \n')

        t = template.Template('{% load custom %}{% inclusion_only_unlimited_args_from_template 37 42 56 89 %}')
        self.assertEqual(t.render(c), 'inclusion_only_unlimited_args_from_template - Expected result: 37, 42, 56, 89\n')

    def test_inclusion_tag_registration(self):
        # Test that the decorators preserve the decorated function's docstring, name and attributes.
        self.verify_tag(custom.inclusion_no_params, 'inclusion_no_params')
        self.verify_tag(custom.inclusion_one_param, 'inclusion_one_param')
        self.verify_tag(custom.inclusion_explicit_no_context, 'inclusion_explicit_no_context')
        self.verify_tag(custom.inclusion_no_params_with_context, 'inclusion_no_params_with_context')
        self.verify_tag(custom.inclusion_params_and_context, 'inclusion_params_and_context')
        self.verify_tag(custom.inclusion_two_params, 'inclusion_two_params')
        self.verify_tag(custom.inclusion_one_default, 'inclusion_one_default')
        self.verify_tag(custom.inclusion_unlimited_args, 'inclusion_unlimited_args')
        self.verify_tag(custom.inclusion_only_unlimited_args, 'inclusion_only_unlimited_args')
        self.verify_tag(custom.inclusion_tag_without_context_parameter, 'inclusion_tag_without_context_parameter')
        self.verify_tag(custom.inclusion_tag_use_l10n, 'inclusion_tag_use_l10n')
        self.verify_tag(custom.inclusion_tag_current_app, 'inclusion_tag_current_app')
        self.verify_tag(custom.inclusion_unlimited_args_kwargs, 'inclusion_unlimited_args_kwargs')

    def test_15070_current_app(self):
        """
        Test that inclusion tag passes down `current_app` of context to the
        Context of the included/rendered template as well.
        """
        c = template.Context({})
        t = template.Template('{% load custom %}{% inclusion_tag_current_app %}')
        self.assertEqual(t.render(c).strip(), 'None')

        c.current_app = 'advanced'
        self.assertEqual(t.render(c).strip(), 'advanced')

    def test_15070_use_l10n(self):
        """
        Test that inclusion tag passes down `use_l10n` of context to the
        Context of the included/rendered template as well.
        """
        c = template.Context({})
        t = template.Template('{% load custom %}{% inclusion_tag_use_l10n %}')
        self.assertEqual(t.render(c).strip(), 'None')

        c.use_l10n = True
        self.assertEqual(t.render(c).strip(), 'True')

    def test_assignment_tags(self):
        c = template.Context({'value': 42})

        t = template.Template('{% load custom %}{% assignment_no_params as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_no_params - Expected result')

        t = template.Template('{% load custom %}{% assignment_one_param 37 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_one_param - Expected result: 37')

        t = template.Template('{% load custom %}{% assignment_explicit_no_context 37 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_explicit_no_context - Expected result: 37')

        t = template.Template('{% load custom %}{% assignment_no_params_with_context as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_no_params_with_context - Expected result (context value: 42)')

        t = template.Template('{% load custom %}{% assignment_params_and_context 37 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_params_and_context - Expected result (context value: 42): 37')

        t = template.Template('{% load custom %}{% assignment_two_params 37 42 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_two_params - Expected result: 37, 42')

        t = template.Template('{% load custom %}{% assignment_one_default 37 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_one_default - Expected result: 37, hi')

        t = template.Template('{% load custom %}{% assignment_one_default 37 two="hello" as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_one_default - Expected result: 37, hello')

        t = template.Template('{% load custom %}{% assignment_one_default one=99 two="hello" as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_one_default - Expected result: 99, hello')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_one_default' received unexpected keyword argument 'three'",
            template.Template, '{% load custom %}{% assignment_one_default 99 two="hello" three="foo" as var %}')

        t = template.Template('{% load custom %}{% assignment_one_default 37 42 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_one_default - Expected result: 37, 42')

        t = template.Template('{% load custom %}{% assignment_unlimited_args 37 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_unlimited_args - Expected result: 37, hi')

        t = template.Template('{% load custom %}{% assignment_unlimited_args 37 42 56 89 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_unlimited_args - Expected result: 37, 42, 56, 89')

        t = template.Template('{% load custom %}{% assignment_only_unlimited_args as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_only_unlimited_args - Expected result: ')

        t = template.Template('{% load custom %}{% assignment_only_unlimited_args 37 42 56 89 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_only_unlimited_args - Expected result: 37, 42, 56, 89')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_one_param' tag takes at least 2 arguments and the second last argument must be 'as'",
            template.Template, '{% load custom %}{% assignment_one_param 37 %}The result is: {{ var }}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_one_param' tag takes at least 2 arguments and the second last argument must be 'as'",
            template.Template, '{% load custom %}{% assignment_one_param 37 as %}The result is: {{ var }}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_one_param' tag takes at least 2 arguments and the second last argument must be 'as'",
            template.Template, '{% load custom %}{% assignment_one_param 37 ass var %}The result is: {{ var }}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_two_params' received too many positional arguments",
            template.Template, '{% load custom %}{% assignment_two_params 37 42 56 as var %}The result is: {{ var }}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_one_default' received too many positional arguments",
            template.Template, '{% load custom %}{% assignment_one_default 37 42 56 as var %}The result is: {{ var }}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_one_default' did not receive value\(s\) for the argument\(s\): 'one'",
            template.Template, '{% load custom %}{% assignment_one_default as var %}The result is: {{ var }}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_unlimited_args' did not receive value\(s\) for the argument\(s\): 'one'",
            template.Template, '{% load custom %}{% assignment_unlimited_args as var %}The result is: {{ var }}')

        t = template.Template('{% load custom %}{% assignment_unlimited_args_kwargs 37 40|add:2 56 eggs="scrambled" four=1|add:3 as var %}The result is: {{ var }}')
        self.assertEqual(t.render(c), 'The result is: assignment_unlimited_args_kwargs - Expected result: 37, 42, 56 / eggs=scrambled, four=4')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_unlimited_args_kwargs' received some positional argument\(s\) after some keyword argument\(s\)",
            template.Template, '{% load custom %}{% assignment_unlimited_args_kwargs 37 40|add:2 eggs="scrambled" 56 four=1|add:3 as var %}The result is: {{ var }}')

        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_unlimited_args_kwargs' received multiple values for keyword argument 'eggs'",
            template.Template, '{% load custom %}{% assignment_unlimited_args_kwargs 37 eggs="scrambled" eggs="scrambled" as var %}The result is: {{ var }}')

    def test_class_based_tags(self):
        c = template.Context({'value': 42})

        t = template.Template('{% load class_based %}a{% cb_one_tag %}b')
        self.assertEqual(t.render(c), 'ab')

        t = template.Template('{% load class_based %}a{% cb_two_tags %}b{% end_cb_two_tags %}c')
        self.assertEqual(t.render(c), 'abc')

        t = template.Template('{% load class_based %}a{% cb_to_upper %}b{% end_cb_to_upper %}c')
        self.assertEqual(t.render(c), 'aBc')

        t = template.Template('{% load class_based %}a{% cb_with_middle %}b{% middle %}c{% end_cb_with_middle %}d')
        self.assertEqual(t.render(c), 'abcd')

        t = template.Template('{% load class_based %}a{% cb_render_second %}b{% middle %}c{% end_cb_render_second %}d')
        self.assertEqual(t.render(c), 'acd')

        t = template.Template('{% load class_based %}a{% cb_render_second2 %}b{% middle %}c{% end_cb_render_second2 %}d')
        self.assertEqual(t.render(c), 'acd')

        t = template.Template('{% load class_based %}a{% cb_optional_middle %}b{% middle %}c{% end_cb_optional_middle %}d')
        self.assertEqual(t.render(c), 'abcd')

        t = template.Template('{% load class_based %}a{% cb_optional_middle %}b{% end_cb_optional_middle %}c')
        self.assertEqual(t.render(c), 'abc')

        t = template.Template('{% load class_based %}a{% cb_repeating_middle %}b{% end_cb_repeating_middle %}c')
        self.assertEqual(t.render(c), 'abc')

        t = template.Template('{% load class_based %}a{% cb_repeating_middle %}b{% middle %}c{% end_cb_repeating_middle %}d')
        self.assertEqual(t.render(c), 'abcd')

        t = template.Template('{% load class_based %}a{% cb_repeating_middle %}b{% middle %}c{% middle %}d{% end_cb_repeating_middle %}e')
        self.assertEqual(t.render(c), 'abcde')

        t = template.Template('{% load class_based %}a{% cb_repeating_middle %}b{% middle %}c{% middle %}d{% middle %}e{% end_cb_repeating_middle %}f')
        self.assertEqual(t.render(c), 'abcdef')

        t = template.Template('{% load class_based %}a{% cb_one_or_more_middle %}b{% middle %}c{% end_cb_one_or_more_middle %}d')
        self.assertEqual(t.render(c), 'abcd')

        t = template.Template('{% load class_based %}a{% cb_one_or_more_middle %}b{% middle %}c{% middle %}d{% end_cb_one_or_more_middle %}e')
        self.assertEqual(t.render(c), 'abcde')

        t = template.Template('{% load class_based %}a{% cb_one_or_more_middle %}b{% middle %}c{% middle %}d{% middle %}e{% end_cb_one_or_more_middle %}f')
        self.assertEqual(t.render(c), 'abcdef')

        t = template.Template('{% load class_based %}a{% cb_reverse_blocks %}b{% next %}c{% next %}d{% next %}e{% end_cb_reverse_blocks %}f')
        self.assertEqual(t.render(c), 'aedcbf')

        t = template.Template('{% load class_based %}_{% cb_complex1 %}_{% B %}_{% C %}_{% D %}_{% end_cb_complex1 %}_')
        self.assertEqual(t.render(c), '______')

        t = template.Template('{% load class_based %}_{% cb_complex1 %}_{% B %}_{% C %}_{% D %}_{% E %}_{% end_cb_complex1 %}_')
        self.assertEqual(t.render(c), '_______')

        t = template.Template('{% load class_based %}_{% cb_complex1 %}_{% A %}_{% A %}_{% B %}_{% C %}_{% D %}_{% E %}_{% end_cb_complex1 %}_')
        self.assertEqual(t.render(c), '_________')

        t = template.Template('{% load class_based %}_{% cb_complex1 %}_{% A %}_{% A %}_{% B %}_{% C %}_{% D %}_{% E %}_{% end_cb_complex1 %}_')
        self.assertEqual(t.render(c), '_________')

        t = template.Template('{% load class_based %}_{% cb_complex1 %}_{% A %}_{% A %}_{% B %}_{% C %}_{% D %}_{% D %}_{% E %}_{% end_cb_complex1 %}_')
        self.assertEqual(t.render(c), '__________')

        t = template.Template('{% load class_based %}{% cb_print_params %}')
        self.assertEqual(t.render(c), '')

        t = template.Template('{% load class_based %}{% cb_print_params 5 %}')
        self.assertEqual(t.render(c), '5')

        t = template.Template('{% load class_based %}{% cb_print_params value value %}')
        self.assertEqual(t.render(c), 'value value')

        t = template.Template('{% load class_based %}{% cb_print_params2 start start2 %}...{% end_cb_print_params2 end end2 %}')
        self.assertEqual(t.render(c), 'start start2...end end2')

        t = template.Template('{% load class_based %}{% cb_print_and_resolv value value 5 %}')
        self.assertEqual(t.render(c), '42 42 5')

        # Template tag exceptions
        six.assertRaisesRegex(self, template.TemplateSyntaxError, 'Expected "middle" template tag, but found "end_cb_one_or_more_middle" instead.',
                    template.Template, '{% load class_based %}a{% cb_one_or_more_middle %}b{% end_cb_one_or_more_middle %}c')

        # Test grammar
        g = template.Grammar('start middle* end')
        self.assertEqual(g.is_simple, False)
        self.assertEqual(g.first_tagname, 'start')
        self.assertEqual(g.as_string(), 'start middle* end')

        g = template.Grammar('simple_tag')
        self.assertEqual(g.is_simple, True)
        self.assertEqual(g.first_tagname, 'simple_tag')
        self.assertEqual(g.as_string(), 'simple_tag')

        # Grammar exceptions

        six.assertRaisesRegex(self, template.GrammarException, 'invalid_tag# is not a valid template tag.',
                    template.Grammar, 'invalid_tag#')

        six.assertRaisesRegex(self, template.GrammarException, 'The first template tag should not repeat.',
                    template.Grammar, 'repeat_first*')

        six.assertRaisesRegex(self, template.GrammarException, 'The first template tag should not repeat.',
                    template.Grammar, 'repeat_first2+ other_tag')

        six.assertRaisesRegex(self, template.GrammarException, 'The last template tag should not repeat.',
                    template.Grammar, 'repeat_last last+')

        six.assertRaisesRegex(self, template.GrammarException, 'The template tag middle is defined more than once.',
                    template.Grammar, 'first middle other_middle+ again_another* middle? middle last')

        six.assertRaisesRegex(self, template.GrammarException, 'No template tags given.',
                    template.Grammar, '')

        # Registering of template tags in a library
        l = template.Library()

        @l.tag
        class Tag(template.TemplateTag):
            """ Tag documentation """
            grammar = template.Grammar('start end')

        self.assertEqual(l.tags['start'].grammar, Tag.grammar)
        self.assertEqual(l.tags['start'].__doc__, Tag.__doc__)

        class TagWithoutGrammar(template.TemplateTag):
            pass

        six.assertRaisesRegex(self, template.TemplateSyntaxError, 'TemplateTag has no valid grammar.',
                        l.tag, TagWithoutGrammar)

        # Registering a tag, which is defined by a function, but without
        # grammar should get an UnknownGrammar instance attached
        l = template.Library()
        def tag_without_grammar(parser, token): pass
        l.tag(tag_without_grammar)

        self.assertEqual(l.tags.get('tag_without_grammar', None), tag_without_grammar)
        self.assertEqual(isinstance(tag_without_grammar.grammar, template.UnknownGrammar), True)
        self.assertEqual(tag_without_grammar.grammar.first_tagname, 'tag_without_grammar')


    def test_assignment_tag_registration(self):
        # Test that the decorators preserve the decorated function's docstring, name and attributes.
        self.verify_tag(custom.assignment_no_params, 'assignment_no_params')
        self.verify_tag(custom.assignment_one_param, 'assignment_one_param')
        self.verify_tag(custom.assignment_explicit_no_context, 'assignment_explicit_no_context')
        self.verify_tag(custom.assignment_no_params_with_context, 'assignment_no_params_with_context')
        self.verify_tag(custom.assignment_params_and_context, 'assignment_params_and_context')
        self.verify_tag(custom.assignment_one_default, 'assignment_one_default')
        self.verify_tag(custom.assignment_two_params, 'assignment_two_params')
        self.verify_tag(custom.assignment_unlimited_args, 'assignment_unlimited_args')
        self.verify_tag(custom.assignment_only_unlimited_args, 'assignment_only_unlimited_args')
        self.verify_tag(custom.assignment_unlimited_args, 'assignment_unlimited_args')
        self.verify_tag(custom.assignment_unlimited_args_kwargs, 'assignment_unlimited_args_kwargs')
        self.verify_tag(custom.assignment_tag_without_context_parameter, 'assignment_tag_without_context_parameter')

    def test_assignment_tag_missing_context(self):
        # The 'context' parameter must be present when takes_context is True
        six.assertRaisesRegex(self, template.TemplateSyntaxError,
            "'assignment_tag_without_context_parameter' is decorated with takes_context=True so it must have a first argument of 'context'",
            template.Template, '{% load custom %}{% assignment_tag_without_context_parameter 123 as var %}')
