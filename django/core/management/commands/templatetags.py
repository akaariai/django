from __future__ import unicode_literals

from optparse import make_option

from django.core.management.base import BaseCommand
from django.template.base import get_library, LibraryGrammar
from django.template import InvalidTemplateLibrary


class Command(BaseCommand):
    help = "Prints the template tags in this application"
    args = '<library>'

    def handle(self, library_name=None, **options):
        if library_name:
            try:
                lib = get_library(library_name)
                grammar = lib.get_grammar()
                print grammar.as_string()
            except InvalidTemplateLibrary:
                print 'Template tag library not found.'
        else:
            print LibraryGrammar.from_builtins().as_string(self.style)
