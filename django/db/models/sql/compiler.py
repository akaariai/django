from django.utils.six.moves import zip

from django.core.exceptions import FieldError
from django.db import transaction
from django.db.backends.util import truncate_name
from django.db.models.loading import get_models
from django.db.models.constants import LOOKUP_SEP
from django.db.models.query_utils import select_related_descend
from django.db.models.sql.constants import (SINGLE, MULTI, ORDER_DIR,
        GET_ITERATOR_CHUNK_SIZE, SelectInfo)
from django.db.models.sql.datastructures import EmptyResultSet
from django.db.models.sql.expressions import SQLEvaluator
from django.db.models.sql.query import get_order_dir, Query
from django.db.utils import DatabaseError
from django.utils import six

class ALL_TABLES(object):

    def __contains__(self, val):
        return True
ALL_TABLES = ALL_TABLES()

_table_to_cols_cache = {}
def get_cols_by_table(tbl):
    try:
        return _table_to_cols_cache[tbl]
    except KeyError:
        models = get_models(include_auto_created=True, only_installed=False)
        for model in models:
            if model._meta.db_table == tbl:
                _table_to_cols_cache[tbl] = set([f.column for f in model._meta.concrete_model._meta.local_fields])
                return _table_to_cols_cache[tbl]
        raise

class SQLCompiler(object):
    def __init__(self, query, connection, using):
        self.query = query
        self.connection = connection
        self.using = using
        self.quote_cache = {}
        self.duplicate_cols = ALL_TABLES

    def pre_sql_setup(self):
        """
        Does any necessary class setup immediately prior to producing SQL. This
        is for things that can't necessarily be done in __init__ because we
        might not have all the pieces in place at that time.
        # TODO: after the query has been executed, the altered state should be
        # cleaned. We are not using a clone() of the query here.
        """
        if not self.query.tables:
            self.query.join((None, self.query.model._meta.db_table, None, None))
        if (not self.query.select and self.query.default_cols and not
                self.query.included_inherited_models):
            self.query.setup_inherited_models()
        if self.query.select_related and not self.query.related_select_cols:
            self.fill_related_selections()

    def quote_name_unless_alias(self, name):
        """
        A wrapper around connection.ops.quote_name that doesn't quote aliases
        for table names. This avoids problems with some SQL dialects that treat
        quoted strings specially (e.g. PostgreSQL).
        """
        if isinstance(name, tuple):
            return self.quote_pair(name)
        if name in self.quote_cache:
            return self.quote_cache[name]
        if ((name in self.query.alias_map and name not in self.query.table_map) or
                name in self.query.extra_select):
            self.quote_cache[name] = name
            return name
        r = self.connection.ops.quote_name(name)
        self.quote_cache[name] = r
        return r

    def quote_pair(self, pair):
        if pair not in self.quote_cache:
            if pair[1] in self.duplicate_cols:
                self.quote_cache[pair] = (
                    '%s.%s' % (self.quote_name_unless_alias(pair[0]),
                               self.quote_name_unless_alias(pair[1])))
            else:
                self.quote_cache[pair] = self.quote_name_unless_alias(pair[1])
        return self.quote_cache[pair]

    def get_col_output(self, cols, with_aliases):
        col_alias_idx = 0
        result = []
        for tbl_alias, col_sql, alias in cols:
            if tbl_alias is not None:
                col_sql = self.quote_pair((tbl_alias, col_sql))
            if alias is None and with_aliases and col_sql in self.duplicate_cols:
                col_alias_idx += 1
                col_alias = 'Col%d' % col_alias_idx
                result.append('%s AS %s' % (col_sql, col_alias))
            elif alias:
                result.append('%s AS %s' % (col_sql, alias))
            else:
                result.append(col_sql)
        return result

    def get_ordering_output(self, ordering, group_by):
        result = []
        for tbl_alias, col_sql, dir in ordering:
            if not dir:
                result.append(col_sql)
            elif tbl_alias:
                result.append('%s %s' % (self.quote_pair((tbl_alias, col_sql)), dir))
            else:
                result.append('%s %s' % (col_sql, dir))
        group_by_res = []
        for (tbl_alias, col_sql), params in group_by:
            if tbl_alias:
                group_by_res.append((self.quote_pair((tbl_alias, col_sql)), params))
            else:
                group_by_res.append((col_sql, params))
        return result, group_by_res

    def get_distinct_output(self, distinct):
        return []

    def populate_dupe_cols(self):
        self.duplicate_cols = set()
        seen = set()
        for alias in self.query.tables:
            if self.query.alias_refcount[alias]:
                try:
                    cols = get_cols_by_table(self.query.alias_map[alias].table_name)
                except KeyError:
                    self.duplicate_cols = ALL_TABLES
                    break
                self.duplicate_cols.update(cols & seen)
                seen.update(cols)
                
    def as_sql(self, with_limits=True, with_col_aliases=False):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.

        If 'with_limits' is False, any limit/offset information is not included
        in the query.
        """
        if with_limits and self.query.low_mark == self.query.high_mark:
            return '', ()

        self.pre_sql_setup()
        # After executing the query, we must get rid of any joins the query
        # setup created. So, take note of alias counts before the query ran.
        # However we do not want to get rid of stuff done in pre_sql_setup(),
        # as the pre_sql_setup will modify query state in a way that forbids
        # another run of it.
        self.refcounts_before = self.query.alias_refcount.copy()
        cols = self.get_columns()
        ordering, group_by = self.get_ordering()
        distinct_fields = self.get_distinct()

        # This must come after 'select', 'ordering' and 'distinct' -- see
        # docstring of get_from_clause() for details.
        from_, f_params = self.get_from_clause()
        self.populate_dupe_cols()
        ordering, ordering_group_by = self.get_ordering_output(ordering, group_by)
        distinct_fields = self.get_distinct_output(distinct_fields)
        out_cols = self.get_col_output(cols, with_col_aliases)

        qn = self.quote_name_unless_alias

        where, w_params = self.query.where.as_sql(qn=qn, connection=self.connection)
        having, h_params = self.query.having.as_sql(qn=qn, connection=self.connection)
        params = []
        for val in six.itervalues(self.query.extra_select):
            params.extend(val[1])

        result = ['SELECT']

        if self.query.distinct:
            result.append(self.connection.ops.distinct_sql(distinct_fields))

        result.append(', '.join(out_cols + [self.quote_name_unless_alias(a) for a in self.query.ordering_aliases]))

        result.append('FROM')
        result.extend(from_)
        params.extend(f_params)

        if where:
            result.append('WHERE %s' % where)
            params.extend(w_params)

        grouping, gb_params = self.get_grouping(ordering_group_by)
        if grouping:
            if distinct_fields:
                raise NotImplementedError(
                    "annotate() + distinct(fields) not implemented.")
            if not ordering:
                ordering = self.connection.ops.force_no_ordering()
            result.append('GROUP BY %s' % ', '.join(grouping))
            params.extend(gb_params)

        if having:
            result.append('HAVING %s' % having)
            params.extend(h_params)

        if ordering:
            result.append('ORDER BY %s' % ', '.join(ordering))

        if with_limits:
            if self.query.high_mark is not None:
                result.append('LIMIT %d' % (self.query.high_mark - self.query.low_mark))
            if self.query.low_mark:
                if self.query.high_mark is None:
                    val = self.connection.ops.no_limit_value()
                    if val:
                        result.append('LIMIT %d' % val)
                result.append('OFFSET %d' % self.query.low_mark)

        if self.query.select_for_update and self.connection.features.has_select_for_update:
            # If we've been asked for a NOWAIT query but the backend does not support it,
            # raise a DatabaseError otherwise we could get an unexpected deadlock.
            nowait = self.query.select_for_update_nowait
            if nowait and not self.connection.features.has_select_for_update_nowait:
                raise DatabaseError('NOWAIT is not supported on this database backend.')
            result.append(self.connection.ops.for_update_sql(nowait=nowait))

        # Finally do cleanup - get rid of the joins we created above.
        self.query.reset_refcounts(self.refcounts_before)

        return ' '.join(result), tuple(params)

    def as_nested_sql(self):
        """
        Perform the same functionality as the as_sql() method, returning an
        SQL string and parameters. However, the alias prefixes are bumped
        beforehand (in a copy -- the current query isn't changed), and any
        ordering is removed if the query is unsliced.

        Used when nesting this query inside another.
        """
        obj = self.query.clone()
        if obj.low_mark == 0 and obj.high_mark is None:
            # If there is no slicing in use, then we can safely drop all ordering
            obj.clear_ordering(True)
        obj.bump_prefix()
        return obj.get_compiler(connection=self.connection).as_sql()

    def get_columns(self):
        """
        Returns the list of column pairs to use in the select statement. If no
        columns have been specified, returns all columns relating to fields in
        the model.

        Returns the columns as 3-tupes: (tbl_alias, col, col_alias). This
        will then generate SQL like SELECT tbl_alias.col AS col_alias FROM ...
        """
        qn = self.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name
        result = [(None, '(%s)' % col[0], qn2(alias)) for alias, col in self.query.extra_select.items()]
        if self.query.select:
            only_load = self.deferred_to_columns()
            for col, _ in self.query.select:
                if isinstance(col, (list, tuple)):
                    alias, column = col
                    table = self.query.alias_map[alias].table_name
                    if table in only_load and column not in only_load[table]:
                        continue
                    result.append((alias, column, None))
                else:
                    col_sql = col.as_sql(qn, self.connection)
                    if hasattr(col, 'alias'):
                        result.append((None, col_sql, col.alias))
                    else:
                        result.append((None, col_sql, None))
        elif self.query.default_cols:
            result.extend(self.get_default_columns())

        max_name_length = self.connection.ops.max_name_length()
        result.extend([
            (
                None,
                aggregate.as_sql(qn, self.connection),
                alias is not None
                    and qn(truncate_name(alias, max_name_length))
                    or None
            )
            for alias, aggregate in self.query.aggregate_select.items()
        ])

        for r, _ in self.query.related_select_cols:
            result.append(r)
        return result

    def get_default_columns(self, start_alias=None, opts=None, from_parent=None):
        """
        Computes the default columns for selecting every field in the base
        model. Will sometimes be called to pull in related models (e.g. via
        select_related), in which case "opts" and "start_alias" will be given
        to provide a starting point for the traversal.
        """
        result = []
        if opts is None:
            opts = self.query.model._meta
        only_load = self.deferred_to_columns()
        seen = self.query.included_inherited_models.copy()
        if start_alias:
            seen[None] = start_alias
        for field, model in opts.get_fields_with_model():
            if from_parent and model is not None and issubclass(from_parent, model):
                # Avoid loading data for already loaded parents.
                continue
            alias = self.query.join_parent_model(opts, model, start_alias, seen)
            table = self.query.alias_map[alias].table_name
            if table in only_load and field.column not in only_load[table]:
                continue
            result.append((alias, field.column, None))
        return result

    def get_distinct(self):
        """
        Returns a quoted list of fields to use in DISTINCT ON part of the query.

        Note that this method can alter the tables in the query, and thus it
        must be called before get_from_clause().
        """
        result = []
        opts = self.query.model._meta
        for name in self.query.distinct_fields:
            parts = name.split(LOOKUP_SEP)
            field, col, alias, _, _ = self._setup_joins(parts, opts, None)
            col, alias = self._final_join_removal(col, alias)
            result.append((alias, col))
        return result


    def get_ordering(self):
        """
        Returns a tuple containing a list representing the SQL elements in the
        "order by" clause, and the list of SQL elements that need to be added
        to the GROUP BY clause as a result of the ordering.

        Also sets the ordering_aliases attribute on this instance to a list of
        extra aliases needed in the select.

        Determining the ordering SQL can change the tables we need to include,
        so this should be run *before* get_from_clause().
        """
        if self.query.extra_order_by:
            ordering = self.query.extra_order_by
        elif not self.query.default_ordering:
            ordering = self.query.order_by
        else:
            ordering = (self.query.order_by
                        or self.query.model._meta.ordering
                        or [])
        qn = self.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name
        distinct = self.query.distinct
        result = []
        group_by = []
        ordering_aliases = []
        if self.query.standard_ordering:
            asc, desc = ORDER_DIR['ASC']
        else:
            asc, desc = ORDER_DIR['DESC']

        # It's possible, due to model inheritance, that normal usage might try
        # to include the same field more than once in the ordering. We track
        # the table/column pairs we use and discard any after the first use.
        processed_pairs = set()
        for field in ordering:
            if field == '?':
                result.append((None, self.connection.ops.random_function_sql(), None))
                continue
            if isinstance(field, int):
                if field < 0:
                    order = desc
                    field = -field
                else:
                    order = asc
                result.append((None, str(field), order))
                group_by.append(((None, str(field)), []))
                continue
            col, order = get_order_dir(field, asc)
            if col in self.query.aggregate_select:
                result.append((None, qn(col), order))
                continue
            if '.' in field:
                # This came in through an extra(order_by=...) addition. Pass it
                # on verbatim.
                table, col = col.split('.', 1)
                if (table, col) not in processed_pairs:
                    elt = '%s.%s' % (qn(table), col)
                    processed_pairs.add((table, col))
                    if not distinct:
                        result.append((None, elt, order))
                        group_by.append(((None, elt), []))
            elif get_order_dir(field)[0] not in self.query.extra_select:
                # 'col' is of the form 'field' or 'field1__field2' or
                # '-field1__field2__field', etc.
                for table, col, order in self.find_ordering_name(field,
                        self.query.model._meta, default_order=asc):
                    if (table, col) not in processed_pairs:
                        processed_pairs.add((table, col))
                        if distinct:
                            ordering_aliases.append((table, col))
                        result.append((table, col, order))
                        group_by.append(((table, col), []))
            else:
                elt = qn2(col)
                if distinct:
                    ordering_aliases.append(elt)
                result.append((None, elt, order))
                extra_sel = self.query.extra_select[col]
                group_by.append(((None, extra_sel[0]), extra_sel[1]))
        self.query.ordering_aliases = ordering_aliases
        return result, group_by

    def find_ordering_name(self, name, opts, alias=None, default_order='ASC',
            already_seen=None):
        """
        Returns the table alias (the name might be ambiguous, the alias will
        not be) and column name for ordering by the given 'name' parameter.
        The 'name' is of the form 'field1__field2__...__fieldN'.
        """
        name, order = get_order_dir(name, default_order)
        pieces = name.split(LOOKUP_SEP)
        field, col, alias, joins, opts = self._setup_joins(pieces, opts, alias)

        # If we get to this point and the field is a relation to another model,
        # append the default ordering for that model.
        if field.rel and len(joins) > 1 and opts.ordering:
            # Firstly, avoid infinite loops.
            if not already_seen:
                already_seen = set()
            join_tuple = tuple([self.query.alias_map[j].table_name for j in joins])
            if join_tuple in already_seen:
                raise FieldError('Infinite loop caused by ordering.')
            already_seen.add(join_tuple)

            results = []
            for item in opts.ordering:
                results.extend(self.find_ordering_name(item, opts, alias,
                        order, already_seen))
            return results
        col, alias = self._final_join_removal(col, alias)
        return [(alias, col, order)]

    def _setup_joins(self, pieces, opts, alias):
        """
        A helper method for get_ordering and get_distinct. This method will
        call query.setup_joins, handle refcounts and then promote the joins.

        Note that get_ordering and get_distinct must produce same target
        columns on same input, as the prefixes of get_ordering and get_distinct
        must match. Executing SQL where this is not true is an error.
        """
        if not alias:
            alias = self.query.get_initial_alias()
        field, target, opts, joins, _ = self.query.setup_joins(
            pieces, opts, alias)
        # We will later on need to promote those joins that were added to the
        # query afresh above.
        joins_to_promote = [j for j in joins if self.query.alias_refcount[j] < 2]
        alias = joins[-1]
        col = target.column
        if not field.rel:
            # To avoid inadvertent trimming of a necessary alias, use the
            # refcount to show that we are referencing a non-relation field on
            # the model.
            self.query.ref_alias(alias)

        # Must use left outer joins for nullable fields and their relations.
        # Ordering or distinct must not affect the returned set, and INNER
        # JOINS for nullable fields could do this.
        self.query.promote_joins(joins_to_promote)
        return field, col, alias, joins, opts

    def _final_join_removal(self, col, alias):
        """
        A helper method for get_distinct and get_ordering. This method will
        trim extra not-needed joins from the tail of the join chain.

        This is very similar to what is done in trim_joins, but we will
        trim LEFT JOINS here. It would be a good idea to consolidate this
        method and query.trim_joins().
        """
        if alias:
            while 1:
                join = self.query.alias_map[alias]
                if col != join.rhs_join_col:
                    break
                self.query.unref_alias(alias)
                alias = join.lhs_alias
                col = join.lhs_join_col
        return col, alias

    def get_from_clause(self):
        """
        Returns a list of strings that are joined together to go after the
        "FROM" part of the query, as well as a list any extra parameters that
        need to be included. Sub-classes, can override this to create a
        from-clause via a "select".

        This should only be called after any SQL construction methods that
        might change the tables we need. This means the select columns,
        ordering and distinct must be done first.
        """
        result = []
        qn = self.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name
        first = True
        from_params = []
        for alias in self.query.tables:
            if not self.query.alias_refcount[alias]:
                continue
            try:
                name, alias, join_type, lhs, lhs_col, col, _, join_field = self.query.alias_map[alias]
            except KeyError:
                # Extra tables can end up in self.tables, but not in the
                # alias_map if they aren't in a join. That's OK. We skip them.
                continue
            alias_str = (alias != name and ' %s' % alias or '')
            if join_type and not first:
                if join_field and hasattr(join_field, 'get_extra_join_sql'):
                    extra_cond, extra_params = join_field.get_extra_join_sql(
                        self.connection, qn, lhs, alias)
                    from_params.extend(extra_params)
                else:
                    extra_cond = ""
                result.append('%s %s%s ON (%s.%s = %s.%s%s)' %
                              (join_type, qn(name), alias_str, qn(lhs),
                               qn2(lhs_col), qn(alias), qn2(col), extra_cond))
            else:
                connector = not first and ', ' or ''
                result.append('%s%s%s' % (connector, qn(name), alias_str))
            first = False
        for t in self.query.extra_tables:
            alias, unused = self.query.table_alias(t)
            # Only add the alias if it's not already present (the table_alias()
            # calls increments the refcount, so an alias refcount of one means
            # this is the only reference.
            if alias not in self.query.alias_map or self.query.alias_refcount[alias] == 1:
                connector = not first and ', ' or ''
                result.append('%s%s' % (connector, qn(alias)))
                first = False
        return result, from_params

    def get_grouping(self, ordering_group_by):
        """
        Returns a tuple representing the SQL elements in the "group by" clause.
        """
        qn = self.quote_name_unless_alias
        result, params = [], []
        if self.query.group_by is not None:
            select_cols = self.query.select + self.query.related_select_cols
            # Just the column, not the fields.
            select_cols = [s[0] for s in select_cols]
            if (len(self.query.model._meta.fields) == len(self.query.select)
                    and self.connection.features.allows_group_by_pk):
                self.query.group_by = [
                    (self.query.model._meta.db_table, self.query.model._meta.pk.column)
                ]
                select_cols = []
            seen = set()
            cols = self.query.group_by + select_cols
            for col in cols:
                if isinstance(col, (list, tuple)):
                    sql = qn((col[0], col[1], None))
                elif hasattr(col, 'as_sql'):
                    sql = col.as_sql(qn, self.connection)
                else:
                    sql = '(%s)' % str(col)
                if sql not in seen:
                    result.append(sql)
                    seen.add(sql)

            # Still, we need to add all stuff in ordering (except if the backend can
            # group by just by PK).
            if ordering_group_by and not self.connection.features.allows_group_by_pk:
                for order, order_params in ordering_group_by:
                    # Even if we have seen the same SQL string, it might have
                    # different params, so, we add same SQL in "has params" case.
                    if order not in seen or params:
                        result.append(order)
                        params.extend(order_params)
                        seen.add(order)

            # Unconditionally add the extra_select items.
            for extra_select, extra_params in self.query.extra_select.values():
                sql = '(%s)' % str(extra_select)
                result.append(sql)
                params.extend(extra_params)

        return result, params

    def fill_related_selections(self, opts=None, root_alias=None, cur_depth=1,
            requested=None, restricted=None, nullable=None):
        """
        Fill in the information needed for a select_related query. The current
        depth is measured as the number of connections away from the root model
        (for example, cur_depth=1 means we are looking at models with direct
        connections to the root model).
        """
        if not restricted and self.query.max_depth and cur_depth > self.query.max_depth:
            # We've recursed far enough; bail out.
            return

        if not opts:
            opts = self.query.get_meta()
            root_alias = self.query.get_initial_alias()
            self.query.related_select_cols = []
        only_load = self.query.get_loaded_field_names()

        # Setup for the case when only particular related fields should be
        # included in the related selection.
        if requested is None:
            if isinstance(self.query.select_related, dict):
                requested = self.query.select_related
                restricted = True
            else:
                restricted = False

        for f, model in opts.get_fields_with_model():
            # The get_fields_with_model() returns None for fields that live
            # in the field's local model. So, for those fields we want to use
            # the f.model - that is the field's local model.
            field_model = model or f.model
            if not select_related_descend(f, restricted, requested,
                                          only_load.get(field_model)):
                continue
            table = f.rel.to._meta.db_table
            promote = nullable or f.null
            alias = self.query.join_parent_model(opts, model, root_alias, {})

            alias = self.query.join((alias, table, f.column,
                    f.rel.get_related_field().column),
                    promote=promote, join_field=f)
            columns = self.get_default_columns(start_alias=alias, opts=f.rel.to._meta)
            self.query.related_select_cols.extend(
                SelectInfo(col, field) for col, field in zip(columns, f.rel.to._meta.fields))
            if restricted:
                next = requested.get(f.name, {})
            else:
                next = False
            new_nullable = f.null or promote
            self.fill_related_selections(f.rel.to._meta, alias, cur_depth + 1,
                    next, restricted, new_nullable)

        if restricted:
            related_fields = [
                (o.field, o.model)
                for o in opts.get_all_related_objects()
                if o.field.unique
            ]
            for f, model in related_fields:
                if not select_related_descend(f, restricted, requested,
                                              only_load.get(model), reverse=True):
                    continue

                alias = self.query.join_parent_model(opts, f.rel.to, root_alias, {})
                table = model._meta.db_table
                alias = self.query.join(
                    (alias, table, f.rel.get_related_field().column, f.column),
                    promote=True, join_field=f
                )
                from_parent = (opts.model if issubclass(model, opts.model)
                               else None)
                columns = self.get_default_columns(start_alias=alias,
                                                   opts=model._meta, from_parent=from_parent)
                self.query.related_select_cols.extend(
                    SelectInfo(col, field) for col, field
                    in zip(columns, model._meta.fields))
                next = requested.get(f.related_query_name(), {})
                # Use True here because we are looking at the _reverse_ side of
                # the relation, which is always nullable.
                new_nullable = True

                self.fill_related_selections(model._meta, table, cur_depth+1,
                    next, restricted, new_nullable)

    def deferred_to_columns(self):
        """
        Converts the self.deferred_loading data structure to mapping of table
        names to sets of column names which are to be loaded. Returns the
        dictionary.
        """
        columns = {}
        self.query.deferred_to_data(columns, self.query.deferred_to_columns_cb)
        return columns

    def results_iter(self):
        """
        Returns an iterator over the results from executing this query.
        """
        resolve_columns = hasattr(self, 'resolve_columns')
        fields = None
        has_aggregate_select = bool(self.query.aggregate_select)
        # Set transaction dirty if we're using SELECT FOR UPDATE to ensure
        # a subsequent commit/rollback is executed, so any database locks
        # are released.
        if self.query.select_for_update and transaction.is_managed(self.using):
            transaction.set_dirty(self.using)
        for rows in self.execute_sql(MULTI):
            for row in rows:
                if resolve_columns:
                    if fields is None:
                        # We only set this up here because
                        # related_select_cols isn't populated until
                        # execute_sql() has been called.

                        # We also include types of fields of related models that
                        # will be included via select_related() for the benefit
                        # of MySQL/MySQLdb when boolean fields are involved
                        # (#15040).

                        # This code duplicates the logic for the order of fields
                        # found in get_columns(). It would be nice to clean this up.
                        if self.query.select:
                            fields = [f.field for f in self.query.select]
                        else:
                            fields = self.query.model._meta.fields
                        fields = fields + [f.field for f in self.query.related_select_cols]

                        # If the field was deferred, exclude it from being passed
                        # into `resolve_columns` because it wasn't selected.
                        only_load = self.deferred_to_columns()
                        if only_load:
                            db_table = self.query.model._meta.db_table
                            fields = [f for f in fields if db_table in only_load and
                                      f.column in only_load[db_table]]
                    row = self.resolve_columns(row, fields)

                if has_aggregate_select:
                    aggregate_start = len(self.query.extra_select) + len(self.query.select)
                    aggregate_end = aggregate_start + len(self.query.aggregate_select)
                    row = tuple(row[:aggregate_start]) + tuple([
                        self.query.resolve_aggregate(value, aggregate, self.connection)
                        for (alias, aggregate), value
                        in zip(self.query.aggregate_select.items(), row[aggregate_start:aggregate_end])
                    ]) + tuple(row[aggregate_end:])

                yield row

    def execute_sql(self, result_type=MULTI):
        """
        Run the query against the database and returns the result(s). The
        return value is a single data item if result_type is SINGLE, or an
        iterator over the results if the result_type is MULTI.

        result_type is either MULTI (use fetchmany() to retrieve all rows),
        SINGLE (only retrieve a single row), or None. In this last case, the
        cursor is returned if any query is executed, since it's used by
        subclasses such as InsertQuery). It's possible, however, that no query
        is needed, as the filters describe an empty set. In that case, None is
        returned, to avoid any unnecessary database interaction.
        """
        try:
            sql, params = self.as_sql()
            if not sql:
                raise EmptyResultSet
        except EmptyResultSet:
            if result_type == MULTI:
                return iter([])
            else:
                return

        cursor = self.connection.cursor()
        cursor.execute(sql, params)

        if not result_type:
            return cursor
        if result_type == SINGLE:
            if self.query.ordering_aliases:
                return cursor.fetchone()[:-len(self.query.ordering_aliases)]
            return cursor.fetchone()

        # The MULTI case.
        if self.query.ordering_aliases:
            result = order_modified_iter(cursor, len(self.query.ordering_aliases),
                    self.connection.features.empty_fetchmany_value)
        else:
            result = iter((lambda: cursor.fetchmany(GET_ITERATOR_CHUNK_SIZE)),
                    self.connection.features.empty_fetchmany_value)
        if not self.connection.features.can_use_chunked_reads:
            # If we are using non-chunked reads, we return the same data
            # structure as normally, but ensure it is all read into memory
            # before going any further.
            return list(result)
        return result


class SQLInsertCompiler(SQLCompiler):
    def placeholder(self, field, val):
        if field is None:
            # A field value of None means the value is raw.
            return val
        elif hasattr(field, 'get_placeholder'):
            # Some fields (e.g. geo fields) need special munging before
            # they can be inserted.
            return field.get_placeholder(val, self.connection)
        else:
            # Return the common case for the placeholder
            return '%s'

    def as_sql(self):
        # We don't need quote_name_unless_alias() here, since these are all
        # going to be column names (so we can avoid the extra overhead).
        qn = self.connection.ops.quote_name
        opts = self.query.model._meta
        result = ['INSERT INTO %s' % qn(opts.db_table)]

        has_fields = bool(self.query.fields)
        fields = self.query.fields if has_fields else [opts.pk]
        result.append('(%s)' % ', '.join([qn(f.column) for f in fields]))

        if has_fields:
            params = values = [
                [
                    f.get_db_prep_save(getattr(obj, f.attname) if self.query.raw else f.pre_save(obj, True), connection=self.connection)
                    for f in fields
                ]
                for obj in self.query.objs
            ]
        else:
            values = [[self.connection.ops.pk_default_value()] for obj in self.query.objs]
            params = [[]]
            fields = [None]
        can_bulk = (not any(hasattr(field, "get_placeholder") for field in fields) and
            not self.return_id and self.connection.features.has_bulk_insert)

        if can_bulk:
            placeholders = [["%s"] * len(fields)]
        else:
            placeholders = [
                [self.placeholder(field, v) for field, v in zip(fields, val)]
                for val in values
            ]
            # Oracle Spatial needs to remove some values due to #10888
            params = self.connection.ops.modify_insert_params(placeholders, params)
        if self.return_id and self.connection.features.can_return_id_from_insert:
            params = params[0]
            col = "%s.%s" % (qn(opts.db_table), qn(opts.pk.column))
            result.append("VALUES (%s)" % ", ".join(placeholders[0]))
            r_fmt, r_params = self.connection.ops.return_insert_id()
            # Skip empty r_fmt to allow subclasses to customize behaviour for
            # 3rd party backends. Refs #19096.
            if r_fmt:
                result.append(r_fmt % col)
                params += r_params
            return [(" ".join(result), tuple(params))]
        if can_bulk:
            result.append(self.connection.ops.bulk_insert_sql(fields, len(values)))
            return [(" ".join(result), tuple([v for val in values for v in val]))]
        else:
            return [
                (" ".join(result + ["VALUES (%s)" % ", ".join(p)]), vals)
                for p, vals in zip(placeholders, params)
            ]

    def execute_sql(self, return_id=False):
        assert not (return_id and len(self.query.objs) != 1)
        self.return_id = return_id
        cursor = self.connection.cursor()
        for sql, params in self.as_sql():
            cursor.execute(sql, params)
        if not (return_id and cursor):
            return
        if self.connection.features.can_return_id_from_insert:
            return self.connection.ops.fetch_returned_insert_id(cursor)
        return self.connection.ops.last_insert_id(cursor,
                self.query.model._meta.db_table, self.query.model._meta.pk.column)


class SQLDeleteCompiler(SQLCompiler):
    def as_sql(self):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.
        """
        assert len(self.query.tables) == 1, \
                "Can only delete from one table at a time."
        qn = self.quote_name_unless_alias
        result = ['DELETE FROM %s' % qn(self.query.tables[0])]
        where, params = self.query.where.as_sql(qn=qn, connection=self.connection)
        if where:
            result.append('WHERE %s' % where)
        return ' '.join(result), tuple(params)

class SQLUpdateCompiler(SQLCompiler):
    def as_sql(self):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.
        """
        self.pre_sql_setup()
        if not self.query.values:
            return '', ()
        table = self.query.tables[0]
        qn = self.quote_name_unless_alias
        result = ['UPDATE %s' % qn(table)]
        result.append('SET')
        values, update_params = [], []
        for field, model, val in self.query.values:
            if hasattr(val, 'prepare_database_save'):
                val = val.prepare_database_save(field)
            else:
                val = field.get_db_prep_save(val, connection=self.connection)

            # Getting the placeholder for the field.
            if hasattr(field, 'get_placeholder'):
                placeholder = field.get_placeholder(val, self.connection)
            else:
                placeholder = '%s'

            if hasattr(val, 'evaluate'):
                val = SQLEvaluator(val, self.query, allow_joins=False)
            name = field.column
            if hasattr(val, 'as_sql'):
                sql, params = val.as_sql(qn, self.connection)
                values.append('%s = %s' % (qn(name), sql))
                update_params.extend(params)
            elif val is not None:
                values.append('%s = %s' % (qn(name), placeholder))
                update_params.append(val)
            else:
                values.append('%s = NULL' % qn(name))
        if not values:
            return '', ()
        result.append(', '.join(values))
        where, params = self.query.where.as_sql(qn=qn, connection=self.connection)
        if where:
            result.append('WHERE %s' % where)
        return ' '.join(result), tuple(update_params + params)

    def execute_sql(self, result_type):
        """
        Execute the specified update. Returns the number of rows affected by
        the primary update query. The "primary update query" is the first
        non-empty query that is executed. Row counts for any subsequent,
        related queries are not available.
        """
        cursor = super(SQLUpdateCompiler, self).execute_sql(result_type)
        rows = cursor and cursor.rowcount or 0
        is_empty = cursor is None
        del cursor
        for query in self.query.get_related_updates():
            aux_rows = query.get_compiler(self.using).execute_sql(result_type)
            if is_empty:
                rows = aux_rows
                is_empty = False
        return rows

    def pre_sql_setup(self):
        """
        If the update depends on results from other tables, we need to do some
        munging of the "where" conditions to match the format required for
        (portable) SQL updates. That is done here.

        Further, if we are going to be running multiple updates, we pull out
        the id values to update at this point so that they don't change as a
        result of the progressive updates.
        """
        self.query.select_related = False
        self.query.clear_ordering(True)
        super(SQLUpdateCompiler, self).pre_sql_setup()
        count = self.query.count_active_tables()
        if not self.query.related_updates and count == 1:
            return

        # We need to use a sub-select in the where clause to filter on things
        # from other tables.
        query = self.query.clone(klass=Query)
        query.bump_prefix()
        query.extra = {}
        query.select = []
        query.add_fields([query.model._meta.pk.name])
        # Recheck the count - it is possible that fiddling with the select
        # fields above removes tables from the query. Refs #18304.
        count = query.count_active_tables()
        if not self.query.related_updates and count == 1:
            return

        must_pre_select = count > 1 and not self.connection.features.update_can_self_select

        # Now we adjust the current query: reset the where clause and get rid
        # of all the tables we don't need (since they're in the sub-select).
        self.query.where = self.query.where_class()
        if self.query.related_updates or must_pre_select:
            # Either we're using the idents in multiple update queries (so
            # don't want them to change), or the db backend doesn't support
            # selecting from the updating table (e.g. MySQL).
            idents = []
            for rows in query.get_compiler(self.using).execute_sql(MULTI):
                idents.extend([r[0] for r in rows])
            self.query.add_filter(('pk__in', idents))
            self.query.related_ids = idents
        else:
            # The fast path. Filters and updates in one query.
            self.query.add_filter(('pk__in', query))
        for alias in self.query.tables[1:]:
            self.query.alias_refcount[alias] = 0

class SQLAggregateCompiler(SQLCompiler):
    def as_sql(self, qn=None):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.
        """
        if qn is None:
            qn = self.quote_name_unless_alias

        sql = ('SELECT %s FROM (%s) subquery' % (
            ', '.join([
                aggregate.as_sql(qn, self.connection)
                for aggregate in self.query.aggregate_select.values()
            ]),
            self.query.subquery)
        )
        params = self.query.sub_params
        return (sql, params)

class SQLDateCompiler(SQLCompiler):
    def results_iter(self):
        """
        Returns an iterator over the results from executing this query.
        """
        resolve_columns = hasattr(self, 'resolve_columns')
        if resolve_columns:
            from django.db.models.fields import DateTimeField
            fields = [DateTimeField()]
        else:
            from django.db.backends.util import typecast_timestamp
            needs_string_cast = self.connection.features.needs_datetime_string_cast

        offset = len(self.query.extra_select)
        for rows in self.execute_sql(MULTI):
            for row in rows:
                date = row[offset]
                if resolve_columns:
                    date = self.resolve_columns(row, fields)[offset]
                elif needs_string_cast:
                    date = typecast_timestamp(str(date))
                yield date


def order_modified_iter(cursor, trim, sentinel):
    """
    Yields blocks of rows from a cursor. We use this iterator in the special
    case when extra output columns have been added to support ordering
    requirements. We must trim those extra columns before anything else can use
    the results, since they're only needed to make the SQL valid.
    """
    for rows in iter((lambda: cursor.fetchmany(GET_ITERATOR_CHUNK_SIZE)),
            sentinel):
        yield [r[:-trim] for r in rows]
