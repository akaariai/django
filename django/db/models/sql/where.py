"""
Code to manage the creation and SQL rendering of 'where' constraints.
"""

from __future__ import absolute_import

import collections
import datetime

from django.utils import tree
from django.utils import six
from django.db.models.sql.datastructures import EmptyResultSet

# Connection types
AND = 'AND'
OR = 'OR'

class EmptyShortCircuit(Exception):
    """
    Internal exception used to indicate that a "matches nothing" node should be
    added to the where-clause.
    """
    pass

class WhereNode(tree.Node):
    """
    Used to represent the SQL where-clause.

    The class is tied to the Query class that created it (in order to create
    the correct SQL).

    The children in this tree are usually either Q-like objects or lists of
    [table_alias, field_name, db_type, lookup_type, value_annotation, params].
    However, a child could also be any class with as_sql() and relabel_aliases() methods.
    """
    default = AND

    def add(self, data, connector):
        """
        Add a node to the where-tree. If the data is a list or tuple, it is
        expected to be of the form (obj, lookup_type, value), where obj is
        a Constraint object, and is then slightly munged before being stored
        (to avoid storing any reference to field objects). Otherwise, the 'data'
        is stored unchanged and can be any class with an 'as_sql()' method.
        """
        if not isinstance(data, (list, tuple)):
            super(WhereNode, self).add(data, connector)
            return

        obj, lookup_type, value = data
        if isinstance(lookup_type, six.string_types):
            raise ValueError('Strings not allowed as lookup_type - must be instances of "Lookup"')
        if isinstance(value, collections.Iterator):
            # Consume any generators immediately, so that we can determine
            # emptiness and transform any non-empty values correctly.
            value = list(value)

        # The "value_annotation" parameter is used to pass auxilliary information
        # about the value(s) to the query construction. Specifically, datetime
        # and empty values need special handling. Other types could be used
        # here in the future (using Python types is suggested for consistency).
        if isinstance(value, datetime.datetime):
            value_annotation = datetime.datetime
        elif hasattr(value, 'value_annotation'):
            value_annotation = value.value_annotation
        else:
            value_annotation = bool(value)

        if hasattr(obj, "prepare"):
            value = obj.prepare(lookup_type, value)

        super(WhereNode, self).add(
                (obj, lookup_type, value_annotation, value), connector)

    def as_sql(self, qn, connection):
        """
        Returns the SQL version of the where clause and the value to be
        substituted in. Returns '', [] if this node matches everything,
        None, [] if this node is empty, and raises EmptyResultSet if this
        node can't match anything.
        """
        # Note that the logic here is made slightly more complex than
        # necessary because there are two kind of empty nodes: Nodes
        # containing 0 children, and nodes that are known to match everything.
        # A match-everything node is different than empty node (which also
        # technically matches everything) for backwards compatibility reasons.
        # Refs #5261.
        result = []
        result_params = []
        everything_childs, nothing_childs = 0, 0
        non_empty_childs = len(self.children)

        for child in self.children:
            try:
                if hasattr(child, 'as_sql'):
                    sql, params = child.as_sql(qn=qn, connection=connection)
                else:
                    # A leaf node in the tree.
                    sql, params = self.make_atom(child, qn, connection)
            except EmptyResultSet:
                nothing_childs += 1
            else:
                if sql:
                    result.append(sql)
                    result_params.extend(params)
                else:
                    if sql is None:
                        # Skip empty childs totally.
                        non_empty_childs -= 1
                        continue
                    everything_childs += 1
            # Check if this node matches nothing or everything.
            # First check the amount of full nodes and empty nodes
            # to make this node empty/full.
            if self.connector == AND:
                full_needed, empty_needed = non_empty_childs, 1
            else:
                full_needed, empty_needed = 1, non_empty_childs
            # Now, check if this node is full/empty using the
            # counts.
            if empty_needed - nothing_childs <= 0:
                if self.negated:
                    return '', []
                else:
                    raise EmptyResultSet
            if full_needed - everything_childs <= 0:
                if self.negated:
                    raise EmptyResultSet
                else:
                    return '', []

        if non_empty_childs == 0:
            # All the child nodes were empty, so this one is empty, too.
            return None, []
        conn = ' %s ' % self.connector
        sql_string = conn.join(result)
        if sql_string:
            if self.negated:
                # Some backends (Oracle at least) need parentheses
                # around the inner SQL in the negated case, even if the
                # inner SQL contains just a single expression.
                sql_string = 'NOT (%s)' % sql_string
            elif len(result) > 1:
                sql_string = '(%s)' % sql_string
        return sql_string, result_params

    def make_atom(self, child, qn, connection):
        """
        Turn a tuple (Constraint(table_alias, column_name, db_type),
        lookup, value_annotation, params) into valid SQL.

        The first item of the tuple may also be an Aggregate.

        Returns the string for the SQL fragment and the parameters to use for
        it.
        """
        lvalue, lookup, value_annotation, params_or_value = child
        return lookup.make_atom(lvalue, value_annotation, params_or_value, qn, connection)


    def relabel_aliases(self, change_map, node=None):
        """
        Relabels the alias values of any children. 'change_map' is a dictionary
        mapping old (current) alias values to the new values.
        """
        if not node:
            node = self
        for pos, child in enumerate(node.children):
            if hasattr(child, 'relabel_aliases'):
                child.relabel_aliases(change_map)
            elif isinstance(child, tree.Node):
                self.relabel_aliases(change_map, child)
            elif isinstance(child, (list, tuple)):
                if isinstance(child[0], (list, tuple)):
                    elt = list(child[0])
                    if elt[0] in change_map:
                        elt[0] = change_map[elt[0]]
                        node.children[pos] = (tuple(elt),) + child[1:]
                else:
                    child[0].relabel_aliases(change_map)

                # Check if the query value also requires relabelling
                if hasattr(child[3], 'relabel_aliases'):
                    child[3].relabel_aliases(change_map)

class EverythingNode(object):
    """
    A node that matches everything.
    """

    def as_sql(self, qn=None, connection=None):
        return '', []

    def relabel_aliases(self, change_map, node=None):
        return

class NothingNode(object):
    """
    A node that matches nothing.
    """
    def as_sql(self, qn=None, connection=None):
        raise EmptyResultSet

    def relabel_aliases(self, change_map, node=None):
        return

class ExtraWhere(object):
    def __init__(self, sqls, params):
        self.sqls = sqls
        self.params = params

    def as_sql(self, qn=None, connection=None):
        sqls = ["(%s)" % sql for sql in self.sqls]
        return " AND ".join(sqls), tuple(self.params or ())
