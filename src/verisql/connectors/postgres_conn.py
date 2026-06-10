from typing import Any

from verisql.connectors.base import ColumnStats, ensure_limited, guard_mutation

try:
    import psycopg
except ImportError as e:  # pragma: no cover
    raise ImportError("Install with `pip install verisql[postgres]`") from e


class PostgresConnector:
    """Postgres adapter. Runs every probe inside a READ ONLY, auto-rollback transaction
    so the verifier can never mutate the target database, even if a check has a bug.
    """

    dialect = "postgres"

    def __init__(self, conn: "psycopg.Connection", schema: str = "public"):
        self._conn = conn
        self._schema = schema

    @classmethod
    def from_dsn(cls, dsn: str, schema: str = "public") -> "PostgresConnector":
        # autocommit off; we wrap reads in explicit read-only txns
        conn = psycopg.connect(dsn, autocommit=False)
        return cls(conn, schema=schema)

    def _read(self, sql: str, params: tuple | None = None) -> list[tuple[Any, ...]]:
        """Execute inside a guaranteed-rolled-back read-only transaction."""
        with self._conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            try:
                cur.execute(sql, params)
                rows = cur.fetchall() if cur.description else []
            finally:
                cur.execute("ROLLBACK")
        return rows

    def list_tables(self) -> list[str]:
        rows = self._read(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (self._schema,),
        )
        return [r[0] for r in rows]

    def list_columns(self, table: str) -> list[str]:
        rows = self._read(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s AND table_schema = %s",
            (table, self._schema),
        )
        return [r[0] for r in rows]

    def execute_readonly(self, sql: str, max_rows: int = 100) -> list[tuple[Any, ...]]:
        guard_mutation(sql, self.dialect)
        sql = ensure_limited(sql, max_rows)
        return self._read(sql)

    def explain(self, sql: str) -> str:
        guard_mutation(sql, self.dialect)
        # plain EXPLAIN — no ANALYZE, so the query is never executed
        rows = self._read(f"EXPLAIN {sql.rstrip(';')}")
        return "\n".join(str(r[0]) for r in rows)

    def column_stats(self, table: str, column: str) -> ColumnStats | None:
        """Read min/max/distinct from pg_stats catalog — zero table scan."""
        try:
            rows = self._read(
                "SELECT null_frac, n_distinct, histogram_bounds::text "
                "FROM pg_stats WHERE schemaname = %s AND tablename = %s AND attname = %s",
                (self._schema, table, column),
            )
        except Exception:
            return None
        if not rows:
            return None
        null_frac, n_distinct, hist = rows[0]
        lo = hi = None
        if hist:
            # histogram_bounds renders as '{v1,v2,...}'
            inner = hist.strip("{}")
            if inner:
                parts = inner.split(",")
                lo, hi = parts[0], parts[-1]
        approx = int(n_distinct) if n_distinct and n_distinct > 0 else None
        return ColumnStats(min=lo, max=hi, approx_distinct=approx, null_fraction=null_frac)
