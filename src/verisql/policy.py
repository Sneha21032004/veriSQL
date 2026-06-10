"""Business-invariant policy: declarative assertions a correct result must satisfy.

Example policy.yaml:

    invariants:
      - "revenue >= 0"
      - "active_users <= total_users"
      - "refund_rate <= 1"
    required_filters:
      orders: ["created_at"]
      events: ["event_date"]

Invariants are checked against the executed result rows (read-only, capped).
Predicates are parsed with sqlglot and walked by a small interpreter over a fixed
set of comparison/boolean node types. No dynamic code execution is used.
"""
from dataclasses import dataclass, field
from typing import Any
import sqlglot
from sqlglot import expressions as exp


@dataclass
class Policy:
    invariants: list[str] = field(default_factory=list)
    required_filters: dict[str, list[str]] = field(default_factory=dict)
    # PII governance: {table: [pii_column, ...]} — flags any AI query touching
    # governed personal-data columns so access is recorded in the audit trail.
    pii_columns: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Policy":
        return cls(
            invariants=list(data.get("invariants", [])),
            required_filters={k: list(v) for k, v in (data.get("required_filters", {}) or {}).items()},
            pii_columns={k: list(v) for k, v in (data.get("pii_columns", {}) or {}).items()},
        )

    @classmethod
    def from_yaml(cls, path: str) -> "Policy":
        import yaml  # optional dep; only needed if loading from file
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(yaml.safe_load(f) or {})


class InvariantEvaluator:
    """Check a sqlglot-parsed boolean predicate against a row dict via a fixed-node walker."""

    def __init__(self, predicate_sql: str):
        self.source = predicate_sql
        self.expr = sqlglot.parse_one(predicate_sql, read="duckdb")

    def check(self, row: dict[str, Any]) -> bool | None:
        """Return True/False, or None if the predicate cannot be resolved for this row
        (column absent or NULL operand)."""
        try:
            return self._walk(self.expr, {k.lower(): v for k, v in row.items()})
        except _Unresolvable:
            return None

    def _walk(self, node: exp.Expression, row: dict[str, Any]) -> Any:
        if isinstance(node, exp.Column):
            key = node.name.lower()
            if key not in row:
                raise _Unresolvable(f"column {key!r} not in result")
            return row[key]
        if isinstance(node, exp.Literal):
            return float(node.this) if node.is_number else node.this
        if isinstance(node, exp.Boolean):
            return bool(node.this)
        if isinstance(node, exp.Null):
            return None
        if isinstance(node, exp.Paren):
            return self._walk(node.this, row)

        if isinstance(node, (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.EQ, exp.NEQ)):
            left = self._walk(node.this, row)
            right = self._walk(node.expression, row)
            if left is None or right is None:
                raise _Unresolvable("NULL operand")
            return _COMPARATORS[type(node)](left, right)

        if isinstance(node, exp.And):
            return bool(self._walk(node.this, row)) and bool(self._walk(node.expression, row))
        if isinstance(node, exp.Or):
            return bool(self._walk(node.this, row)) or bool(self._walk(node.expression, row))
        if isinstance(node, exp.Not):
            return not bool(self._walk(node.this, row))

        raise _Unresolvable(f"unsupported expression: {type(node).__name__}")


class _Unresolvable(Exception):
    pass


_COMPARATORS = {
    exp.GT: lambda a, b: a > b,
    exp.GTE: lambda a, b: a >= b,
    exp.LT: lambda a, b: a < b,
    exp.LTE: lambda a, b: a <= b,
    exp.EQ: lambda a, b: a == b,
    exp.NEQ: lambda a, b: a != b,
}
