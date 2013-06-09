from __future__ import absolute_import, unicode_literals

from django import template
from django.utils import six
from django.utils.unittest import TestCase

class LibraryGrammarTests(TestCase):
    def test_library_grammar(self):
        # Custom tags
        library = template.get_library('custom')
        grammar = library.get_grammar()
        six.assertRegex(self, grammar.as_string(), 'current_app *::= current_app')
        six.assertRegex(self, grammar.as_string(), 'inclusion_no_params *::= inclusion_no_params')

        # Test class based tags
        library = template.get_library('class_based')
        grammar = library.get_grammar()
        six.assertRegex(self, grammar.as_string(), r'cb_one_tag *::= cb_one_tag')
        six.assertRegex(self, grammar.as_string(), r'cb_print_params2 *::= cb_print_params2 end_cb_print_params2')
        six.assertRegex(self, grammar.as_string(), r'cb_complex1 *::= cb_complex1 A\* B C\? D\+ E\? end_cb_complex1')
