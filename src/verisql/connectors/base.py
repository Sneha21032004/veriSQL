from typing import Protocol, Any, runtime_checkable

# Statements the verifier must never run against a live database.
MUTATION_KEYWORDS = (
    "insert ", "update ", "delete ", "drop ", "alter ",
    "truncate ", "create ", "merge ", "replace ", "attach ", "copy ",
)


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
