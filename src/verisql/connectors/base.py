import re
from typing import Protocol, Any, runtime_checkable

import sqlglot
from sqlglot import expressions as exp

# Statements the verifier must never run against a live database.
MUTATION_KEYWORDS = (
    "insert ", "update ", "delete ", "drop ", "alter ",
    "truncate ", "create ", "merge ", "replace ", "attach ", "copy ",
)

_MUTATION_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.Merge, exp.TruncateTable,
)

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def guard_mutation(sql: str, dialect: str = "duckdb") -> None:
    """Refuse any statement that could mutate the target database.

    Primary: parse the statement and reject mutation AST nodes — immune to
    tricks like leading comments (`-- x\\nDELETE ...`) that defeat naive
    keyword prefix checks. Fallback: comment-stripped keyword check when the
    statement does not parse.
    """
    try:
        parsed = sqlglot.parse(sql, read=dialect)
    except Exception:
        parsed = None

    if parsed:
        for stmt in parsed:
            if stmt is None:
                continue
            if isinstance(stmt, _MUTATION_NODES) or stmt.find(*_MUTATION_NODES):
                raise PermissionError(
                    f"Refusing to execute mutation: {type(stmt).__name__} statement"
                )
        return

    stripped = _BLOCK_COMMENT.sub(" ", _LINE_COMMENT.sub(" ", sql)).lstrip().lower()
    for kw in MUTATION_KEYWORDS:
        if stripped.startswith(kw):
            raise PermissionError(f"Refusing to execute mutation: starts with {kw.strip()}")


def ensure_limited(sql: str, max_rows: int) -> str:
    """Wrap a query in a row cap unless it already carries a LIMIT (word-boundary,
    newline-tolerant — `\\nLIMIT 10` counts)."""
    if re.search(r"\blimit\b", sql, re.IGNORECASE):
        return sql
    return f"SELECT * FROM ({sql.rstrip(';')}) AS _verisql_sub LIMIT {max_rows}"


@runtime_checkable
class Connector(Protocol):
    """Database adapter. Only list_tables/list_columns/execute_readonly are required.

    explain() and column_stats() are optional capabilities; checks that need them
    probe with hasattr and skip gracefully if unsupported.
    """

    dialect: str

    def list_tables(self) -> list[str]: ...
    def list_columns(self, table: str) -> list[str]: ...
    def execute_readonly(self, sql: str, max_rows: int = 100) -> list[tuple[Any, ...]]: ...


class ColumnStats:
    """Lightweight column statistics for aggregate-range sanity checks."""

    __slots__ = ("min", "max", "approx_distinct", "null_fraction")

    def __init__(
        self,
        min: Any = None,
        max: Any = None,
        approx_distinct: int | None = None,
        null_fraction: float | None = None,
    ):
        self.min = min
        self.max = max
        self.approx_distinct = approx_distinct
        self.null_fraction = null_fraction

    def __repr__(self) -> str:
        return (
            f"ColumnStats(min={self.min!r}, max={self.max!r}, "
            f"approx_distinct={self.approx_distinct}, null_fraction={self.null_fraction})"
        )
