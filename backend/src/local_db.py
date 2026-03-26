import os
import psycopg2
import psycopg2.extras
import psycopg2.pool
import logging
from urllib.parse import urlparse


class Result:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count if count is not None else len(self.data)


class TableQuery:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self._select_cols = ["*"]
        self._where = []  # List of (column, operator, value) tuples
        self._order_by = []  # List of (column, desc: bool)
        self._limit = None
        self._offset = None
        self._payload = None
        self._count_mode = None  # "exact" to fetch total count ignoring limit/offset

    def select(self, *cols, count=None):
        if cols:
            self._select_cols = cols
        self._count_mode = count  # Track count mode for execute()
        return self

    def insert(self, payload):
        """Accept a single dict or list of dicts for batch insert."""
        self._payload = payload
        self._action = "insert"
        return self

    def update(self, payload: dict):
        self._payload = payload
        self._action = "update"
        return self

    def upsert(self, payload: dict, on_conflict: str | None = None):
        self._payload = payload
        self._action = "upsert"
        if on_conflict:
            self._upsert_conflict_col = on_conflict
        return self

    def eq(self, col, val):
        """Equal to (=)"""
        self._where.append((col, "=", val))
        return self

    def neq(self, col, val):
        """Not equal to (!=)"""
        self._where.append((col, "!=", val))
        return self

    def gt(self, col, val):
        """Greater than (>)"""
        self._where.append((col, ">", val))
        return self

    def gte(self, col, val):
        """Greater than or equal to (>=)"""
        self._where.append((col, ">=", val))
        return self

    def lt(self, col, val):
        """Less than (<)"""
        self._where.append((col, "<", val))
        return self

    def lte(self, col, val):
        """Less than or equal to (<=)"""
        self._where.append((col, "<=", val))
        return self

    def is_(self, col, val):
        """IS NULL / IS NOT NULL check"""
        if val is None:
            self._where.append((col, "IS", None))
        else:
            self._where.append((col, "IS", val))
        return self

    def ilike(self, col, pattern):
        """Case-insensitive LIKE"""
        self._where.append((col, "ILIKE", pattern))
        return self

    def like(self, col, pattern):
        """Case-sensitive LIKE"""
        self._where.append((col, "LIKE", pattern))
        return self

    def in_(self, col, values):
        """IN (...) filter"""
        self._where.append((col, "IN", list(values)))
        return self

    def not_in(self, col, values):
        """NOT IN (...) filter"""
        self._where.append((col, "NOT_IN", list(values)))
        return self

    def order(self, col, desc=False):
        """Order by column"""
        self._order_by.append((col, desc))
        return self

    def range(self, start, end):
        # Supabase range is inclusive indexes
        self._offset = int(start)
        self._limit = int(end) - int(start) + 1
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    def execute(self):
        conn = self.client.pool.getconn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            def _is_numeric_list(lst):
                """Check if list contains numeric values (embedding) vs strings (text array)."""
                return lst and all(isinstance(x, (int, float)) for x in lst)

            def _prepare_row_values(row_dict, cols):
                """Prepare values and placeholders for a single row."""
                vals = []
                placeholders = []
                for c in cols:
                    v = row_dict.get(c)
                    if isinstance(v, (list, tuple)):
                        if _is_numeric_list(v):
                            # Numeric embedding → cast to vector
                            emb_text = '[' + ','.join(map(str, v)) + ']'
                            vals.append(emb_text)
                            placeholders.append('%s::vector')
                        elif v and isinstance(v[0], dict):
                            # List of dicts (e.g., sources JSONB array) → serialize as JSONB
                            import json as _json
                            vals.append(_json.dumps(v))
                            placeholders.append('%s::jsonb')
                        else:
                            # String/scalar array (e.g., roles) → use PostgreSQL array
                            vals.append(list(v))
                            placeholders.append('%s')
                    elif isinstance(v, dict):
                        # JSONB field → serialize to JSON string
                        import json as _json
                        vals.append(_json.dumps(v))
                        placeholders.append('%s::jsonb')
                    else:
                        vals.append(v)
                        placeholders.append('%s')
                return vals, placeholders

            if getattr(self, '_action', None) == 'insert':
                # Handle both single dict and list of dicts (batch insert)
                payload = self._payload
                rows_to_insert = payload if isinstance(payload, list) else [payload]
                
                if not rows_to_insert:
                    return Result([])
                
                # Get columns from first row
                cols = list(rows_to_insert[0].keys())
                
                all_rows = []
                for row in rows_to_insert:
                    vals, placeholders = _prepare_row_values(row, cols)
                    placeholders_sql = ','.join(placeholders)
                    sql = f"INSERT INTO public.{self.table} ({', '.join(cols)}) VALUES ({placeholders_sql}) RETURNING *"
                    cur.execute(sql, vals)
                    inserted = cur.fetchall()
                    all_rows.extend(inserted)
                
                conn.commit()
                return Result(all_rows)

            if getattr(self, '_action', None) == 'update':
                cols = list(self._payload.keys())
                set_parts = []
                params = []
                for c in cols:
                    v = self._payload[c]
                    if isinstance(v, (list, tuple)):
                        if _is_numeric_list(v):
                            emb_text = '[' + ','.join(map(str, v)) + ']'
                            set_parts.append(f"{c} = %s::vector")
                            params.append(emb_text)
                        else:
                            set_parts.append(f"{c} = %s")
                            params.append(list(v))
                    elif isinstance(v, dict):
                        import json as _json
                        set_parts.append(f"{c} = %s::jsonb")
                        params.append(_json.dumps(v))
                    else:
                        set_parts.append(f"{c} = %s")
                        params.append(v)
                set_clause = ', '.join(set_parts)
                where_clause = ''
                if self._where:
                    # Use new 3-tuple format (col, op, val)
                    conditions = []
                    for col, op, val in self._where:
                        if op == "IS":
                            if val is None:
                                conditions.append(f"{col} IS NULL")
                            else:
                                conditions.append(f"{col} IS NOT NULL")
                        elif op == "IN":
                            if not val:
                                conditions.append("FALSE")
                            else:
                                placeholders = ', '.join(['%s'] * len(val))
                                conditions.append(f"{col} IN ({placeholders})")
                                params.extend(val)
                        elif op == "NOT_IN":
                            if not val:
                                conditions.append("TRUE")
                            else:
                                placeholders = ', '.join(['%s'] * len(val))
                                conditions.append(f"{col} NOT IN ({placeholders})")
                                params.extend(val)
                        else:
                            if isinstance(val, dict):
                                import json as _json
                                conditions.append(f"{col} = %s::jsonb")
                                params.append(_json.dumps(val))
                            else:
                                conditions.append(f"{col} {op} %s")
                                params.append(val)
                    where_clause = ' WHERE ' + ' AND '.join(conditions)
                sql = f"UPDATE public.{self.table} SET {set_clause}{where_clause} RETURNING *"
                cur.execute(sql, params)
                rows = cur.fetchall()
                conn.commit()
                return Result(rows)

            if getattr(self, '_action', None) == 'upsert':
                # Supports both a single dict and a list of dicts (batch upsert).
                conflict_col = getattr(self, '_upsert_conflict_col', None)
                payload = self._payload
                rows_to_upsert = payload if isinstance(payload, list) else [payload]

                if not rows_to_upsert:
                    return Result([])

                if not conflict_col:
                    conflict_col = 'id' if 'id' in rows_to_upsert[0] else None

                cols_all = list(rows_to_upsert[0].keys())
                all_rows = []

                for row_dict in rows_to_upsert:
                    vals, placeholders = _prepare_row_values(row_dict, cols_all)
                    placeholders_sql = ','.join(placeholders)
                    if conflict_col:
                        update_cols = [c for c in cols_all if c != conflict_col]
                        set_clause = ', '.join([f"{c} = EXCLUDED.{c}" for c in update_cols])
                        sql = (
                            f"INSERT INTO public.{self.table} ({', '.join(cols_all)}) "
                            f"VALUES ({placeholders_sql}) "
                            f"ON CONFLICT ({conflict_col}) DO UPDATE SET {set_clause} RETURNING *"
                        )
                    else:
                        sql = (
                            f"INSERT INTO public.{self.table} ({', '.join(cols_all)}) "
                            f"VALUES ({placeholders_sql}) RETURNING *"
                        )
                    cur.execute(sql, vals)
                    all_rows.extend(cur.fetchall())

                conn.commit()
                return Result(all_rows)

            # Default: SELECT
            cols_sql = ', '.join(self._select_cols)
            sql = f"SELECT {cols_sql} FROM public.{self.table}"
            params = []
            where_clause = ''
            
            # Build WHERE clause with operators (col, op, value)
            if self._where:
                conditions = []
                for col, op, val in self._where:
                    if op == "IS":
                        if val is None:
                            conditions.append(f"{col} IS NULL")
                        else:
                            conditions.append(f"{col} IS NOT NULL")
                    elif op == "ILIKE":
                        conditions.append(f"{col} ILIKE %s")
                        params.append(val)
                    elif op == "IN":
                        if not val:
                            conditions.append("FALSE")
                        else:
                            placeholders = ', '.join(['%s'] * len(val))
                            conditions.append(f"{col} IN ({placeholders})")
                            params.extend(val)
                    elif op == "NOT_IN":
                        if not val:
                            conditions.append("TRUE")
                        else:
                            placeholders = ', '.join(['%s'] * len(val))
                            conditions.append(f"{col} NOT IN ({placeholders})")
                            params.extend(val)
                    elif op in ("LIKE",):
                        conditions.append(f"{col} LIKE %s")
                        params.append(val)
                    else:
                        # for dict values serialize to JSONB
                        if isinstance(val, dict):
                            import json as _json
                            conditions.append(f"{col} = %s::jsonb")
                            params.append(_json.dumps(val))
                        else:
                            conditions.append(f"{col} {op} %s")
                            params.append(val)
                where_clause = ' WHERE ' + ' AND '.join(conditions)
            
            # If count="exact" requested, get total count before applying limit/offset/order
            total_count = None
            if self._count_mode == "exact":
                count_sql = f"SELECT COUNT(*) FROM public.{self.table}" + where_clause
                # Use params without limit/offset for count
                cur.execute(count_sql, params[:])
                total_count = cur.fetchone()["count"]
            
            sql += where_clause
            
            # ORDER BY
            if self._order_by:
                order_parts = []
                for col, desc in self._order_by:
                    order_parts.append(f"{col} {'DESC' if desc else 'ASC'}")
                sql += ' ORDER BY ' + ', '.join(order_parts)
            
            if self._limit is not None:
                sql += ' LIMIT %s'
                params.append(self._limit)
            if self._offset is not None:
                sql += ' OFFSET %s'
                params.append(self._offset)
            cur.execute(sql, params)
            rows = cur.fetchall()
            return Result(rows, count=total_count)
        except Exception as e:
            logging.error(
                f"local_db TableQuery execute error on {self.table!r} "
                f"(action={getattr(self, '_action', 'select')}): {e} | sql={locals().get('sql', '<not built>')!r}"
            )
            try:
                conn.rollback()
            except Exception:
                pass
            # Mutations must not silently fail — re-raise so callers know data was not saved
            if getattr(self, '_action', None) in ('insert', 'update', 'upsert'):
                raise
            return Result([])
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                self.client.pool.putconn(conn)
            except Exception:
                pass


class RPCQuery:
    def __init__(self, client, name, payload=None):
        self.client = client
        self.name = name
        self.payload = payload

    def execute(self):
        conn = self.client.pool.getconn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            # Special-case common RPC match_documents
            if self.name == 'match_documents' and isinstance(self.payload, dict):
                q = self.payload.get('query_embedding')
                thr = float(self.payload.get('match_threshold') or 0.0)
                cnt = int(self.payload.get('match_count') or 1)
                # Pass embedding as text literal; assume client provides list-ish
                if isinstance(q, (list, tuple)):
                    emb_text = '[' + ','.join(map(str, q)) + ']'
                else:
                    emb_text = str(q)
                sql = f"select * from public.{self.name}(%s::vector, %s::float, %s::int)"
                cur.execute(sql, (emb_text, thr, cnt))
                rows = cur.fetchall()
                return Result(rows)

            # Generic single-json param RPC
            if self.payload is None:
                cur.execute(f"select * from public.{self.name}()")
                rows = cur.fetchall()
                return Result(rows)
            else:
                cur.execute(f"select * from public.{self.name}(%s)", (psycopg2.extras.Json(self.payload),))
                rows = cur.fetchall()
                return Result(rows)
        except Exception as e:
            logging.error(f"local_db RPC execute error ({self.name}): {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return Result([])
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                self.client.pool.putconn(conn)
            except Exception:
                pass


class LocalDBClient:
    def __init__(self, database_url: str | None = None):
        if database_url is None:
            database_url = os.getenv('DATABASE_URL')
        if not database_url:
            raise RuntimeError('DATABASE_URL is required for LocalDBClient')
        # psycopg2 accepts the URL directly. Use a threaded connection pool to reduce overhead.
        try:
            # minconn=1, maxconn configurable via env
            maxconn = int(os.getenv('PG_MAX_CONN', '10'))
            self.pool = psycopg2.pool.ThreadedConnectionPool(1, maxconn, dsn=database_url)
        except Exception:
            # Fallback to direct connection to preserve compatibility
            conn = psycopg2.connect(database_url)
            class _SimplePool:
                def __init__(self, conn):
                    self._conn = conn
                def getconn(self):
                    return self._conn
                def putconn(self, c):
                    return
            self.pool = _SimplePool(conn)
            self.conn = conn

    def table(self, table_name: str) -> TableQuery:
        return TableQuery(self, table_name)

    def rpc(self, name: str, payload=None) -> RPCQuery:
        return RPCQuery(self, name, payload)
