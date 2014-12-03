import warnings

from django.core.exceptions import FieldError
from django.db.models.constants import LOOKUP_SEP
from django.db.models.expressions import RawSQL, Ref, Random, ColIndexRef
from django.db.models.query_utils import select_related_descend, QueryWrapper
from django.db.models.sql.constants import (CURSOR, SINGLE, MULTI, NO_RESULTS,
        ORDER_DIR, GET_ITERATOR_CHUNK_SIZE)
from django.db.models.sql.datastructures import EmptyResultSet
from django.db.models.sql.query import get_order_dir, Query
from django.db.transaction import TransactionManagementError
from django.db.utils import DatabaseError
from django.utils.deprecation import RemovedInDjango20Warning
from django.utils.six.moves import zip


class SQLCompiler(object):
    def __init__(self, query, connection, using):
        self.query = query
        self.connection = connection
        self.using = using
        self.quote_cache = {'*': '*'}
        self.select = None

    def setup_query(self):
        if all(self.query.alias_refcount[a] == 0 for a in self.query.tables):
            self.query.get_initial_alias()
        if (not self.query.select and self.query.default_cols and not
                self.query.included_inherited_models):
            self.query.setup_inherited_models()
        self.select, klass_info, annotations = self.fill_select()
        self.col_count = len(self.select)
        return self.select, klass_info, annotations

    def pre_sql_setup(self):
        """
        Does any necessary class setup immediately prior to producing SQL. This
        is for things that can't necessarily be done in __init__ because we
        might not have all the pieces in place at that time.
        # TODO: after the query has been executed, the altered state should be
        # cleaned. We are not using a clone() of the query here.
        """
        if self.select is None:
            self.setup_query()
        select, order_by = self.fill_order_by(self.select)
        group_by = self.fill_group_by(select, order_by, self.query.having)
        return select, order_by, group_by

    def fill_group_by(self, select, order_by, having):
        """
        Returns a list of 2-tuples of form (sql, params).
        """
        result = []
        seen = set()
        if self.query.group_by is None:
            return result
        elif self.query.group_by is True:
            for expr, (sql, params), alias in select:
                cols = expr.get_group_by_cols()
                for col in cols:
                    sql, params = self.compile(col)
                    if (sql, tuple(params)) not in seen:
                        result.append((sql, params))
                    seen.add((sql, tuple(params)))
        else:
            for expr in self.query.group_by:
                sql, params = self.compile(expr)
                if (sql, tuple(params)) not in seen:
                    result.append((sql, params))
                seen.add((sql, tuple(params)))
        for expr, (sql, params, _) in order_by:
            if expr.contains_aggregate:
                continue
            if (sql, tuple(params)) not in seen:
                result.append((sql, params))
            seen.add((sql, tuple(params)))
        for col in self.query.having.get_group_by_cols():
            sql, params = self.compile(col)
            if (sql, tuple(params)) not in seen:
                result.append((sql, params))
            seen.add((sql, tuple(params)))
        return result

    def fill_select(self):
        """
        Returns a list of 3-tuples of (expression, (sql, params), alias), and a klass_info
        structure.

        The sql, params is what the expression will produce, and alias is the "AS alias"
        for the column (possibly None).

        The klass_info structure contains the following information:
            - Which model to select
            - Which fields (by position on the first 3-tuple list) to instantiate for this
              model. For example [0, 3, 4, 5]. This list will be in the same order
              Model.__init__ expects *args to be.
            - related_klass_infos: [f, klass_info] to descent into
            - reverse_related_klass_infos: [f, klass_info] to descent into
            - annotations: annotations to this model as {attname, row_pos}
        """
        select = []
        klass_info = None
        annotations = {}
        select_idx = 0
        for alias, sql in self.query.extra_select.items():
            annotations[alias] = select_idx
            select.append((RawSQL(sql), alias))
            select_idx += 1
        assert not (self.query.select and self.query.default_cols)
        if self.query.default_cols:
            select_list = []
            for c in self.get_default_columns():
                select_list.append(select_idx)
                select.append((c, None))
                select_idx += 1
            klass_info = {
                'model': self.query.model,
                'select_fields': select_list,
            }
        # self.query.select is a special case. These columns never go to
        # any model.
        for col in self.query.select:
            select.append((col, None))
            select_idx += 1
        for alias, annotation in self.query.annotation_select.items():
            annotations[alias] = select_idx
            select.append((annotation, alias))
            select_idx += 1

        if self.query.select_related:
            related_klass_infos = self.fill_related_selections(select)
            klass_info['related_klass_infos'] = related_klass_infos

        ret = []
        for col, alias in select:
            ret.append((col, self.compile(col), alias))
        return ret, klass_info, annotations

    def fill_order_by(self, select):
        """
        Returns a list of 2-tuples of form (expr, (sql, params)) for the
        ORDER BY clause.

        The order_by clause can alter the select clause (for example it
        can add aliases to clauses that do not yet have one, or it can
        add totally new select clauses).
        """
        if self.query.extra_order_by:
            ordering = self.query.extra_order_by
        elif not self.query.default_ordering:
            ordering = self.query.order_by
        else:
            ordering = (self.query.order_by
                        or self.query.get_meta().ordering
                        or [])
        if self.query.standard_ordering:
            asc, desc = ORDER_DIR['ASC']
        else:
            asc, desc = ORDER_DIR['DESC']

        order_by = []
        for pos, field in enumerate(ordering):
            if field == '?':
                order_by.append((Random(), asc, False))
                continue
            if isinstance(field, int):
                if field < 0:
                    field = -field
                    int_ord = desc
                order_by.append((ColIndexRef(field), int_ord, True))
                continue
            col, order = get_order_dir(field, asc)
            if col in self.query.annotation_select:
                order_by.append((Ref(col, self.query.annotation_select[col]), order, True))
                continue
            if '.' in field:
                # This came in through an extra(order_by=...) addition. Pass it
                # on verbatim.
                table, col = col.split('.', 1)
                expr = RawSQL(('%s.%s' % (self.quote_name_unless_alias(table), col), []))
                order_by.append((expr, order, False))
                continue
            if not self.query._extra or get_order_dir(field)[0] not in self.query._extra:
                # 'col' is of the form 'field' or 'field1__field2' or
                # '-field1__field2__field', etc.
                order_by.extend(self.find_ordering_name(field, self.query.get_meta(),
                                                        default_order=asc))
            else:
                if col not in self.query.extra_select:
                    order_by.append((RawSQL(self.query.extra[col]), order, False))
                else:
                    order_by.append((Ref(self.quote_name_unless_alias(col), None), order, True))
        result = []
        seen = set()
        select_sql = [t[1] for t in select]
        for expr, order, is_ref in order_by:
            sql, params = self.compile(expr)
            if (sql, tuple(params)) in seen:
                continue
            if self.query.distinct and not self.query.distinct_fields:
                if not is_ref and (sql, params) not in select_sql:
                    select.append((expr, (sql, params), None))
            seen.add((sql, tuple(params)))
            result.append((expr, (sql, params, order)))
        return select, result

    def __call__(self, name):
        """
        Backwards-compatibility shim so that calling a SQLCompiler is equivalent to
        calling its quote_name_unless_alias method.
        """
        warnings.warn(
            "Calling a SQLCompiler directly is deprecated. "
            "Call compiler.quote_name_unless_alias instead.",
            RemovedInDjango20Warning, stacklevel=2)
        return self.quote_name_unless_alias(name)

    def quote_name_unless_alias(self, name):
        """
        A wrapper around connection.ops.quote_name that doesn't quote aliases
        for table names. This avoids problems with some SQL dialects that treat
        quoted strings specially (e.g. PostgreSQL).
        """
        if name in self.quote_cache:
            return self.quote_cache[name]
        if ((name in self.query.alias_map and name not in self.query.table_map) or
                name in self.query.extra_select or name in self.query.external_aliases):
            self.quote_cache[name] = name
            return name
        r = self.connection.ops.quote_name(name)
        self.quote_cache[name] = r
        return r

    def compile(self, node):
        vendor_impl = getattr(
            node, 'as_' + self.connection.vendor, None)
        if vendor_impl:
            return vendor_impl(self, self.connection)
        else:
            return node.as_sql(self, self.connection)

    def as_sql(self, with_limits=True, with_col_aliases=False):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.

        If 'with_limits' is False, any limit/offset information is not included
        in the query.
        """
        if with_limits and self.query.low_mark == self.query.high_mark:
            return '', ()

        # After executing the query, we must get rid of any joins the query
        # setup created. So, take note of alias counts before the query ran.
        # However we do not want to get rid of stuff done in pre_sql_setup(),
        # as the pre_sql_setup will modify query state in a way that forbids
        # another run of it.
        refcounts_before = self.query.alias_refcount.copy()
        select, order_by, group_by = self.pre_sql_setup()
        distinct_fields = self.get_distinct()

        # This must come after 'select', 'ordering' and 'distinct' -- see
        # docstring of get_from_clause() for details.
        from_, f_params = self.get_from_clause()

        where, w_params = self.compile(self.query.where)
        having, h_params = self.compile(self.query.having)
        params = []
        result = ['SELECT']

        if self.query.distinct:
            result.append(self.connection.ops.distinct_sql(distinct_fields))

        out_cols = []
        for _, (s_sql, s_params), alias in select:
            if alias:
                s_sql = '%s AS %s' % (s_sql, self.connection.ops.quote_name(alias))
            params.extend(s_params)
            out_cols.append(s_sql)

        result.append(', '.join(out_cols))

        result.append('FROM')
        result.extend(from_)
        params.extend(f_params)

        if where:
            result.append('WHERE %s' % where)
            params.extend(w_params)

        grouping = []
        for g_sql, g_params in group_by:
            grouping.append(g_sql)
            params.extend(g_params)
        if grouping:
            if distinct_fields:
                raise NotImplementedError(
                    "annotate() + distinct(fields) not implemented.")
            if not order_by:
                order_by = self.connection.ops.force_no_ordering()
            result.append('GROUP BY %s' % ', '.join(grouping))

        if having:
            result.append('HAVING %s' % having)
            params.extend(h_params)

        if order_by:
            ordering = []
            for _, (o_sql, o_params, order) in order_by:
                ordering.append('%s %s' % (o_sql, order))
                params.extend(o_params)
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
            if self.connection.get_autocommit():
                raise TransactionManagementError("select_for_update cannot be used outside of a transaction.")

            # If we've been asked for a NOWAIT query but the backend does not support it,
            # raise a DatabaseError otherwise we could get an unexpected deadlock.
            nowait = self.query.select_for_update_nowait
            if nowait and not self.connection.features.has_select_for_update_nowait:
                raise DatabaseError('NOWAIT is not supported on this database backend.')
            result.append(self.connection.ops.for_update_sql(nowait=nowait))

        # Finally do cleanup - get rid of the joins we created above.
        self.query.reset_refcounts(refcounts_before)
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
        if obj.low_mark == 0 and obj.high_mark is None and not self.query.distinct_fields:
            # If there is no slicing in use, then we can safely drop all ordering
            obj.clear_ordering(True)
        return obj.get_compiler(connection=self.connection).as_sql()

    def get_default_columns(self, start_alias=None, opts=None, from_parent=None):
        """
        Computes the default columns for selecting every field in the base
        model. Will sometimes be called to pull in related models (e.g. via
        select_related), in which case "opts" and "start_alias" will be given
        to provide a starting point for the traversal.

        Returns a list of strings, quoted appropriately for use in SQL
        directly, as well as a set of aliases used in the select statement (if
        'as_pairs' is True, returns a list of (alias, col_name) pairs instead
        of strings as the first component and None as the second component).
        """
        result = []
        if opts is None:
            opts = self.query.get_meta()
        only_load = self.deferred_to_columns()
        if not start_alias:
            start_alias = self.query.get_initial_alias()
        # The 'seen_models' is used to optimize checking the needed parent
        # alias for a given field. This also includes None -> start_alias to
        # be used by local fields.
        seen_models = {None: start_alias}

        for field, model in opts.get_concrete_fields_with_model():
            if from_parent and model is not None and issubclass(from_parent, model):
                # Avoid loading data for already loaded parents.
                continue
            alias = self.query.join_parent_model(opts, model, start_alias,
                                                 seen_models)
            column = field.get_col(alias)
            for seen_model, seen_alias in seen_models.items():
                if seen_model and seen_alias == alias:
                    ancestor_link = seen_model._meta.get_ancestor_link(model)
                    if ancestor_link and ancestor_link.related_field == field:
                        column = ancestor_link.get_col(alias)
                        break
            if field.model in only_load and field.attname not in only_load[field.model]:
                continue
            result.append(column)
        return result

    def get_distinct(self):
        """
        Returns a quoted list of fields to use in DISTINCT ON part of the query.

        Note that this method can alter the tables in the query, and thus it
        must be called before get_from_clause().
        """
        qn = self.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name
        result = []
        opts = self.query.get_meta()

        for name in self.query.distinct_fields:
            parts = name.split(LOOKUP_SEP)
            _, targets, alias, joins, path, _ = self._setup_joins(parts, opts, None)
            targets, alias, _ = self.query.trim_joins(targets, joins, path)
            for target in targets:
                result.append("%s.%s" % (qn(alias), qn2(target.column)))
        return result

    def find_ordering_name(self, name, opts, alias=None, default_order='ASC',
                           already_seen=None):
        """
        Returns the table alias (the name might be ambiguous, the alias will
        not be) and column name for ordering by the given 'name' parameter.
        The 'name' is of the form 'field1__field2__...__fieldN'.
        """
        name, order = get_order_dir(name, default_order)
        pieces = name.split(LOOKUP_SEP)
        field, targets, alias, joins, path, opts = self._setup_joins(pieces, opts, alias)

        # If we get to this point and the field is a relation to another model,
        # append the default ordering for that model unless the attribute name
        # of the field is specified.
        if field.rel and path and opts.ordering and name != field.attname:
            # Firstly, avoid infinite loops.
            if not already_seen:
                already_seen = set()
            join_tuple = tuple(self.query.alias_map[j].table_name for j in joins)
            if join_tuple in already_seen:
                raise FieldError('Infinite loop caused by ordering.')
            already_seen.add(join_tuple)

            results = []
            for item in opts.ordering:
                results.extend(self.find_ordering_name(item, opts, alias,
                                                       order, already_seen))
            return results
        targets, alias, _ = self.query.trim_joins(targets, joins, path)
        return [(t.get_col(alias), order, False) for t in targets]

    def _setup_joins(self, pieces, opts, alias):
        """
        A helper method for fill_order_by and get_distinct.

        Note that get_ordering and get_distinct must produce same target
        columns on same input, as the prefixes of get_ordering and get_distinct
        must match. Executing SQL where this is not true is an error.
        """
        if not alias:
            alias = self.query.get_initial_alias()
        field, targets, opts, joins, path = self.query.setup_joins(
            pieces, opts, alias)
        alias = joins[-1]
        return field, targets, alias, joins, path, opts

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
        params = []
        for alias in self.query.tables:
            if not self.query.alias_refcount[alias]:
                continue
            try:
                from_clause = self.query.alias_map[alias]
            except KeyError:
                # Extra tables can end up in self.tables, but not in the
                # alias_map if they aren't in a join. That's OK. We skip them.
                continue
            clause_sql, clause_params = self.compile(from_clause)
            result.append(clause_sql)
            params.extend(clause_params)
        for t in self.query.extra_tables:
            alias, _ = self.query.table_alias(t)
            # Only add the alias if it's not already present (the table_alias()
            # call increments the refcount, so an alias refcount of one means
            # this is the only reference).
            if alias not in self.query.alias_map or self.query.alias_refcount[alias] == 1:
                result.append(', %s' % self.quote_name_unless_alias(alias))
        return result, params

    def fill_related_selections(self, select, opts=None, root_alias=None, cur_depth=1,
                                requested=None, restricted=None):
        """
        Fill in the information needed for a select_related query. The current
        depth is measured as the number of connections away from the root model
        (for example, cur_depth=1 means we are looking at models with direct
        connections to the root model).
        """
        related_klass_infos = []
        if not restricted and self.query.max_depth and cur_depth > self.query.max_depth:
            # We've recursed far enough; bail out.
            return related_klass_infos

        if not opts:
            opts = self.query.get_meta()
            root_alias = self.query.get_initial_alias()
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
            klass_info = {'model': f.rel.to, 'field': f, 'reverse': False}
            related_klass_infos.append(klass_info)
            select_fields = []
            _, _, _, joins, _ = self.query.setup_joins(
                [f.name], opts, root_alias)
            alias = joins[-1]
            columns = self.get_default_columns(start_alias=alias,
                                               opts=f.rel.to._meta)
            for col in columns:
                select_fields.append(len(select))
                select.append((col, None))
            klass_info['select_fields'] = select_fields
            if restricted:
                next = requested.get(f.name, {})
            else:
                next = False
            next_klass_infos = self.fill_related_selections(
                select, f.rel.to._meta, alias, cur_depth + 1, next, restricted)
            klass_info['related_klass_infos'] = next_klass_infos

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

                _, _, _, joins, _ = self.query.setup_joins(
                    [f.related_query_name()], opts, root_alias)
                alias = joins[-1]
                klass_info = {'model': model, 'field': f, 'reverse': True}
                related_klass_infos.append(klass_info)
                select_fields = []
                columns = self.get_default_columns(
                    start_alias=alias, opts=model._meta)
                for col in columns:
                    select_fields.append(len(select))
                    select.append((col, None))
                klass_info['select_fields'] = select_fields
                next = requested.get(f.related_query_name(), {})
                next_klass_infos = self.fill_related_selections(
                    select, model._meta, alias, cur_depth + 1,
                    next, restricted)
                klass_info['related_klass_infos'] = next_klass_infos
        return related_klass_infos

    def deferred_to_columns(self):
        """
        Converts the self.deferred_loading data structure to mapping of table
        names to sets of column names which are to be loaded. Returns the
        dictionary.
        """
        columns = {}
        self.query.deferred_to_data(columns, self.query.get_loaded_field_names_cb)
        return columns

    def get_converters(self, fields):
        converters = {}
        for i, field in enumerate(fields):
            if field:
                output_field = field.output_field
                backend_converters = self.connection.ops.get_db_converters(output_field)
                field_converters = field.get_db_converters(self.connection)
                if backend_converters or field_converters:
                    converters[i] = (backend_converters, field_converters, output_field)
        return converters

    def apply_converters(self, row, converters):
        row = list(row)
        for pos, (backend_converters, field_converters, field) in converters.items():
            value = row[pos]
            for converter in backend_converters:
                value = converter(value, field)
            for converter in field_converters:
                value = converter(value, self.connection)
            row[pos] = value
        return tuple(row)

    def results_iter(self):
        """
        Returns an iterator over the results from executing this query.
        """
        fields = None
        converters = None
        results = self.execute_sql(MULTI)
        for rows in results:
            for row in rows:
                if fields is None:
                    fields = [s[0] for s in self.select[0:self.col_count]]
                    converters = self.get_converters(fields)
                if converters:
                    row = self.apply_converters(row, converters)
                yield row

    def has_results(self):
        """
        Backends (e.g. NoSQL) can override this in order to use optimized
        versions of "query has any results."
        """
        # This is always executed on a query clone, so we can modify self.query
        self.query.add_extra({'a': 1}, None, None, None, None, None)
        self.query.set_extra_mask(['a'])
        return bool(self.execute_sql(SINGLE))

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
        if not result_type:
            result_type = NO_RESULTS
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
        try:
            cursor.execute(sql, params)
        except Exception:
            cursor.close()
            raise

        if result_type == CURSOR:
            # Caller didn't specify a result_type, so just give them back the
            # cursor to process (and close).
            return cursor
        if result_type == SINGLE:
            try:
                val = cursor.fetchone()
                if val:
                    return val[0:self.col_count]
                return val
            finally:
                # done with the cursor
                cursor.close()
        if result_type == NO_RESULTS:
            cursor.close()
            return

        result = cursor_iter(
            cursor, self.connection.features.empty_fetchmany_value,
            self.col_count
        )
        if not self.connection.features.can_use_chunked_reads:
            try:
                # If we are using non-chunked reads, we return the same data
                # structure as normally, but ensure it is all read into memory
                # before going any further.
                return list(result)
            finally:
                # done with the cursor
                cursor.close()
        return result

    def as_subquery_condition(self, alias, columns, compiler):
        qn = compiler.quote_name_unless_alias
        qn2 = self.connection.ops.quote_name
        if len(columns) == 1:
            sql, params = self.as_sql()
            return '%s.%s IN (%s)' % (qn(alias), qn2(columns[0]), sql), params

        for index, select_col in enumerate(self.query.select):
            lhs_sql, lhs_params = self.compile(select_col)
            rhs = '%s.%s' % (qn(alias), qn2(columns[index]))
            self.query.where.add(
                QueryWrapper('%s = %s' % (lhs_sql, rhs), lhs_params), 'AND')

        sql, params = self.as_sql()
        return 'EXISTS (%s)' % sql, params


class SQLInsertCompiler(SQLCompiler):

    def __init__(self, *args, **kwargs):
        self.return_id = False
        super(SQLInsertCompiler, self).__init__(*args, **kwargs)

    def placeholder(self, field, val):
        if field is None:
            # A field value of None means the value is raw.
            return val
        elif hasattr(field, 'get_placeholder'):
            # Some fields (e.g. geo fields) need special munging before
            # they can be inserted.
            return field.get_placeholder(val, self, self.connection)
        else:
            # Return the common case for the placeholder
            return '%s'

    def as_sql(self):
        # We don't need quote_name_unless_alias() here, since these are all
        # going to be column names (so we can avoid the extra overhead).
        qn = self.connection.ops.quote_name
        opts = self.query.get_meta()
        result = ['INSERT INTO %s' % qn(opts.db_table)]

        has_fields = bool(self.query.fields)
        fields = self.query.fields if has_fields else [opts.pk]
        result.append('(%s)' % ', '.join(qn(f.column) for f in fields))

        if has_fields:
            params = values = [
                [
                    f.get_db_prep_save(
                        getattr(obj, f.attname) if self.query.raw else f.pre_save(obj, True),
                        connection=self.connection
                    ) for f in fields
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
            # Skip empty r_fmt to allow subclasses to customize behavior for
            # 3rd party backends. Refs #19096.
            if r_fmt:
                result.append(r_fmt % col)
                params += r_params
            return [(" ".join(result), tuple(params))]
        if can_bulk:
            result.append(self.connection.ops.bulk_insert_sql(fields, len(values)))
            return [(" ".join(result), tuple(v for val in values for v in val))]
        else:
            return [
                (" ".join(result + ["VALUES (%s)" % ", ".join(p)]), vals)
                for p, vals in zip(placeholders, params)
            ]

    def execute_sql(self, return_id=False):
        assert not (return_id and len(self.query.objs) != 1)
        self.return_id = return_id
        with self.connection.cursor() as cursor:
            for sql, params in self.as_sql():
                cursor.execute(sql, params)
            if not (return_id and cursor):
                return
            if self.connection.features.can_return_id_from_insert:
                return self.connection.ops.fetch_returned_insert_id(cursor)
            return self.connection.ops.last_insert_id(cursor,
                    self.query.get_meta().db_table, self.query.get_meta().pk.column)


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
        where, params = self.compile(self.query.where)
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
            if hasattr(val, 'resolve_expression'):
                val = val.resolve_expression(self.query, allow_joins=False)
            elif hasattr(val, 'prepare_database_save'):
                if field.rel:
                    val = val.prepare_database_save(field)
                else:
                    raise TypeError("Database is trying to update a relational field "
                                    "of type %s with a value of type %s. Make sure "
                                    "you are setting the correct relations" %
                                    (field.__class__.__name__, val.__class__.__name__))
            else:
                val = field.get_db_prep_save(val, connection=self.connection)

            # Getting the placeholder for the field.
            if hasattr(field, 'get_placeholder'):
                placeholder = field.get_placeholder(val, self, self.connection)
            else:
                placeholder = '%s'
            name = field.column
            if hasattr(val, 'as_sql'):
                sql, params = self.compile(val)
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
        where, params = self.compile(self.query.where)
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
        try:
            rows = cursor.rowcount if cursor else 0
            is_empty = cursor is None
        finally:
            if cursor:
                cursor.close()
        for query in self.query.get_related_updates():
            aux_rows = query.get_compiler(self.using).execute_sql(result_type)
            if is_empty and aux_rows:
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
        query._extra = {}
        query.select = []
        query.add_fields([query.get_meta().pk.name])
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
                idents.extend(r[0] for r in rows)
            self.query.add_filter(('pk__in', idents))
            self.query.related_ids = idents
        else:
            # The fast path. Filters and updates in one query.
            self.query.add_filter(('pk__in', query))
        for alias in self.query.tables[1:]:
            self.query.alias_refcount[alias] = 0


class SQLAggregateCompiler(SQLCompiler):
    def as_sql(self):
        """
        Creates the SQL for this query. Returns the SQL string and list of
        parameters.
        """
        # Empty SQL for the inner query is a marker that the inner query
        # isn't going to produce any results. This can happen when doing
        # LIMIT 0 queries (generated by qs[:0]) for example.
        if not self.query.subquery:
            raise EmptyResultSet
        sql, params = [], []
        for annotation in self.query.annotation_select.values():
            agg_sql, agg_params = self.compile(annotation)
            sql.append(agg_sql)
            params.extend(agg_params)
        self.col_count = len(self.query.annotation_select)
        sql = ', '.join(sql)
        params = tuple(params)

        sql = 'SELECT %s FROM (%s) subquery' % (sql, self.query.subquery)
        params = params + self.query.sub_params
        return sql, params


def cursor_iter(cursor, sentinel, col_count):
    """
    Yields blocks of rows from a cursor and ensures the cursor is closed when
    done.
    """
    try:
        for rows in iter((lambda: cursor.fetchmany(GET_ITERATOR_CHUNK_SIZE)),
                         sentinel):
            yield [r[0:col_count] for r in rows]
    finally:
        cursor.close()
