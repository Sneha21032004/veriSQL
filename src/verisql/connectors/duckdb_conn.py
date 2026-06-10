from typing import Any

from verisql.connectors.base import ColumnStats, MUTATION_KEYWORDS

try:
    import duckdb
except ImportError as e:  # pragma: no cover
    raise ImportError("Install with `pip install verisql[duckdb]`") from e


class DuckDBConnector:
    dialect = "duckdb"

    def __init__(self, conn: "duckdb.DuckDBPyConnection"):
        self._conn = conn

    @classmethod
    def from_path(cls, path: str = ":memory:") -> "DuckDBConnector":
        return cls(duckdb.connect(path))

    def list_tables(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        return [r[0] for r in rows]

    def list_columns(self, table: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND table_schema = 'main'",
            [table],
        ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _guard_mutation(sql: str) -> None:
        lowered = sql.lstrip().lower()
        for kw in MUTATION_KEYWORDS:
            if lowered.startswith(kw):
                raise PermissionError(f"Refusing to execute mutation: starts with {kw.strip()}")

    def execute_readonly(self, sql: str, max_rows: int = 100) -> list[tuple[Any, ...]]:
        # DuckDB lacks a hard read-only per-statement flag; we rely on parser refusal.
        self._guard_mutation(sql)
        lowered = sql.lower()
        # Wrap with LIMIT if not present, to keep verifier cheap
        if " limit " not in lowered:
            sql = f"SELECT * FROM ({sql.rstrip(';')}) AS _verisql_sub LIMIT {max_rows}"
        return self._conn.execute(sql).fetchall()

    def explain(self, sql: str) -> str:
        """Return the query plan text without executing the query."""
        self._guard_mutation(sql)
        rows = self._conn.execute(f"EXPLAIN {sql.rstrip(';')}").fetchall()
        return "\n".join(str(r[-1]) for r in rows)

    def column_stats(self, table: str, column: str) -> ColumnStats | None:
        """Min/max/distinct stats from a cheap aggregate scan (sampled-friendly)."""
        try:
            row = self._conn.execute(
                f'SELECT MIN("{column}"), MAX("{column}"), '
                f'approx_count_distinct("{column}"), '
                f'CAST(SUM(CASE WHEN "{column}" IS NULL THEN 1 ELSE 0 END) AS DOUBLE) '
                f'/ NULLIF(COUNT(*), 0) '
                f'FROM "{table}"'
            ).fetchone()
        except Exception:
            return None
        if row is None:
            return None
        return ColumnStats(
            min=row[0], max=row[1], approx_distinct=row[2], null_fraction=row[3]
        )
