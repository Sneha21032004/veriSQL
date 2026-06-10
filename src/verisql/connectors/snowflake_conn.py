from typing import Any

from verisql.connectors.base import ColumnStats, ensure_limited, guard_mutation

try:
    import snowflake.connector as sf
except ImportError as e:  # pragma: no cover
    raise ImportError("Install with `pip install verisql[snowflake]`") from e


class SnowflakeConnector:
    """Snowflake adapter. Reads use the account's read path; mutations are refused
    at the guard. EXPLAIN runs without executing the statement.
    """

    dialect = "snowflake"

    def __init__(self, conn: Any, schema: str | None = None):
        self._conn = conn
        self._schema = schema

    @classmethod
    def connect(cls, **kwargs: Any) -> "SnowflakeConnector":
        schema = kwargs.get("schema")
        return cls(sf.connect(**kwargs), schema=schema)

    def _query(self, sql: str, params: tuple | None = None) -> list[tuple[Any, ...]]:
        cur = self._conn.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    def list_tables(self) -> list[str]:
        where = "WHERE table_schema = %s" if self._schema else ""
        params = (self._schema,) if self._schema else None
        rows = self._query(
            f"SELECT table_name FROM information_schema.tables {where}", params
        )
        return [r[0] for r in rows]

    def list_columns(self, table: str) -> list[str]:
        if self._schema:
            rows = self._query(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s AND table_schema = %s",
                (table.upper(), self._schema),
            )
        else:
            rows = self._query(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (table.upper(),),
            )
        return [r[0] for r in rows]

    def execute_readonly(self, sql: str, max_rows: int = 100) -> list[tuple[Any, ...]]:
        guard_mutation(sql, self.dialect)
        sql = ensure_limited(sql, max_rows)
        return self._query(sql)

    def explain(self, sql: str) -> str:
        guard_mutation(sql, self.dialect)
        rows = self._query(f"EXPLAIN USING TEXT {sql.rstrip(';')}")
        return "\n".join(str(r[-1]) for r in rows)

    def column_stats(self, table: str, column: str) -> ColumnStats | None:
        try:
            row = self._query(
                f'SELECT MIN("{column}"), MAX("{column}"), '
                f'APPROX_COUNT_DISTINCT("{column}") FROM "{table}"'
            )
        except Exception:
            return None
        if not row:
            return None
        mn, mx, approx = row[0]
        return ColumnStats(min=mn, max=mx, approx_distinct=approx)
