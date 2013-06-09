from django.template.base import Node, NodeList, TemplateSyntaxError
import re


class GrammarException(Exception):
    pass


class Grammar(object):
    """
    Generic template tag grammar.

    A grammar is defined by a space separated list of tagnames, optionally with
    a modifier to indicate how many times this tag can appear:
    - *: zero or more times;
    - +: one or more times;
    - ?: zero or one time;
    - (no suffix): exactly one time.

    For instance: 'if elif* else? endif'

    The constraints are:
    - The first and last template tags cannot have any modifier.
    - A tagname should not appear more than once in a single grammar.

    This simple grammar does not automatically parse or validate template tag
    parameters.
    """
    tagname_re = re.compile(r"^[a-zA-Z0-9_]+$")

    class ParseResult(object):
        def __init__(self, parser, parts):
            self.parser = parser
            self.parts = parts

            self.nodelist = NodeList(node for p in parts for node in p.nodelist)

        @property
        def tagname(self):
            return self.parts[0].name

        @property
        def arguments(self):
            return self.parts[0].arguments

    class TemplateTagPart(object):
        def __init__(self, token, name, arguments, nodelist):
            self.token = token
            self.name = name
            self.arguments = arguments
            self.nodelist = nodelist

    def __init__(self, grammar, _split_contents=True):
        # XXX _split_contents is for internal use only.
        if not grammar:
            raise GrammarException('No template tags given.')

        result = []
        for tag in grammar.split():
            if tag.endswith('*') or tag.endswith('+') or tag.endswith('?'):
                tagname, flag = tag[:-1], tag[-1]
            else:
                tagname, flag = tag, None

            if not self.tagname_re.match(tagname):
                raise GrammarException('%s is not a valid template tag name' % tagname)

            if tagname in result:
                raise GrammarException('The template tag %s is defined more than once.' % tagname)

            result.append(tagname)
            result.append(flag)

        # Validate grammar
        if not result:
            raise GrammarException('No template tags given.')
        if result[1] != None:
            raise GrammarException('The first template tag should not repeat.')
        if result[-1] != None:
            raise GrammarException('The last template tag should not repeat.')

        self._split_contents = _split_contents
        self._grammar = result
        self._grammar_string = grammar

        self.first_tagname = result[0]

    @property
    def is_simple(self):
        """ True when this grammar consists of a single tag only. """
        return len(self._grammar) == 2 and self._grammar[1] == None

    def as_string(self, style=None):
        """
        Return a BNF like notation for this grammar.
        """
        return self._grammar_string

    def parse(self, parser, token):
        """
        Apply this generic parser, on a token input, and return a ParseResult.
        """
        parts = []
        _grammar = self._grammar[:]

        while _grammar:
            if token.contents.startswith(_grammar[0]):
                name = _grammar[0]
                current_token = token
                arguments = self.parse_arguments(name, token)

                if len(_grammar) == 2:
                    # Last tag
                    nodelist = NodeList()
                    _grammar = []
                else:
                    if _grammar[1] == '+':
                        _grammar[1] = '*'

                    elif _grammar[1] in (None, '?'):
                        _grammar = _grammar[2:]

                    nodelist = parser.parse(_grammar[::2])
                    token = parser.next_token()

                parts.append(self.TemplateTagPart(current_token, name, arguments, nodelist))

            elif _grammar[1] in ('?', '*'):
                # No match, pop grammar, and try again.
                _grammar = _grammar[2:]

            else:
                # No match. Invalid template.
                raise TemplateSyntaxError('Expected "%s" template tag, but found "%s" instead.' %
                                (_grammar[0], token.contents))

        return self.ParseResult(parser, parts)

    def parse_arguments(self, tagname, token):
        if self._split_contents:
            return token.split_contents()[1:]
        try:
            return token.contents.split(None, 1)[1]
        except IndexError:
            return ''


class UnknownGrammar(Grammar):
    # Grammar-compatible class which will be attached to compile_functions that
    # don't have a grammar yet.
    def __init__(self, tagname):
        self.first_tagname = tagname
        self._grammar_string = '<Unknown Grammar>'

    def parse(self, parser, token):
        raise NotImplementedError

    def as_string(self):
        return self._grammar_string


class TemplateTag(Node):
    """
    Generic template tag.
    """
    grammar = None

    @classmethod
    def as_compile_funcion(cls):
        if not cls.grammar:
            raise TemplateSyntaxError('TemplateTag has no valid grammar.')
        def compile_function(parser, token):
            return cls.parse(parser, token)
        compile_function.grammar = cls.grammar
        compile_function.__name__ = str(cls.grammar.first_tagname)
        compile_function.__doc__ = cls.__doc__
        return cls.grammar.first_tagname, compile_function

    @classmethod
    def parse(cls, parser, token):
        """ Turn parser/token into Node """
        parse_result = cls.grammar.parse(parser, token)
        node = cls.handle_parse_result(parser, parse_result)
        node.parse_result = parse_result
        return node

    @classmethod
    def handle_parse_result(cls, parser, parse_result):
        """ Create Node instance from parse result. """
        node = cls(parser, parse_result)
        return node

    def __init__(self, parser, parse_result):
        pass

    def __iter__(self):
        for node in self.nodelist:
            yield node

    @property
    def nodelist(self):
        return self.parse_result.nodelist

    def render(self, context):
        return self.nodelist.render(context)
