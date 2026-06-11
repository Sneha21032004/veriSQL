"""Deterministic auto-repair for AI-generated SQL.

This is the piece that turns VeriSQL from a flagger into an oracle: for the most
common silent-failure patterns, we don't just warn — we rewrite the AST into the
provably-intended form and re-verify. No LLM involved; every transform is a pure
sqlglot tree rewrite, so the repair is as deterministic as a compiler pass.

    verify -> diagnose -> repair (AST transform) -> re-verify -> ship

Each applied repair is recorded with before/after SQL so the audit trail shows
exactly what changed and why.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import sqlglot
from sqlglot import expressions as exp

from verisql.report import Report
from verisql.verify import verify


@dataclass
class Repair:
    rule: str
    description: str
    before_fragment: str
    after_fragment: str


@dataclass
class RepairResult:
    original_sql: str
    final_sql: str
    repairs: list[Repair] = field(default_factory=list)
    rounds: int = 0
    verified: bool = False
    escalate: bool = False        # True when issues remain that we can't auto-fix
    final_report: Report | None = None

    def summary(self) -> str:
        lines = [
            f"Auto-repair: {len(self.repairs)} fix(es) in {self.rounds} round(s) "
            f"-> {'VERIFIED' if self.verified else 'ESCALATE'}",
        ]
        for r in self.repairs:
            lines.append(f"  [{r.rule}] {r.description}")
            lines.append(f"      - {r.before_fragment}")
            lines.append(f"      + {r.after_fragment}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# transforms — each takes the AST, mutates a copy, and reports what it did
# --------------------------------------------------------------------------- #

def _fix_not_in_null(ast: exp.Expression, repairs: list[Repair]) -> exp.Expression:
    """`x NOT IN (a, NULL, b)` always yields zero rows. Two safe rewrites:

    - literal list: drop the NULL literals (matches universal intent)
    - subquery: append `WHERE col IS NOT NULL` guard inside the subquery
    """
    for node in list(ast.find_all(exp.Not)):
        inner = node.this
        if not isinstance(inner, exp.In):
            continue

        # literal list containing NULL
        if inner.expressions:
            nulls = [e for e in inner.expressions if isinstance(e, exp.Null)]
            if nulls:
                before = node.sql()
                inner.set("expressions", [e for e in inner.expressions if not isinstance(e, exp.Null)])
                repairs.append(Repair(
                    rule="not_in_null_literal",
                    description="NOT IN list contained NULL -> always-empty result; NULL removed",
                    before_fragment=before,
                    after_fragment=node.sql(),
                ))

        # subquery form: NOT IN (SELECT col FROM ...)
        query = inner.args.get("query")
        if query is not None:
            sel = query.this if isinstance(query, exp.Subquery) else query
            if isinstance(sel, exp.Select) and len(sel.expressions) == 1:
                proj = sel.expressions[0]
                col = proj.this if isinstance(proj, exp.Alias) else proj
                if isinstance(col, exp.Column):
                    before = node.sql()
                    guard = exp.Is(this=col.copy(), expression=exp.Null())
                    not_null = exp.Not(this=guard)
                    existing = sel.args.get("where")
                    if existing is not None:
                        sel.set("where", exp.Where(this=exp.And(this=existing.this, expression=not_null)))
                    else:
                        sel.set("where", exp.Where(this=not_null))
                    repairs.append(Repair(
                        rule="not_in_null_subquery",
                        description="NOT IN subquery could yield NULL -> guarded with IS NOT NULL",
                        before_fragment=before,
                        after_fragment=node.sql(),
                    ))
    return ast


def _fix_timestamp_equality(ast: exp.Expression, repairs: list[Repair]) -> exp.Expression:
    """`ts_col = 'YYYY-MM-DD'` matches only midnight -> half-open range [d, d+1)."""
    import re
    ts_name = re.compile(r"(_at$|_ts$|timestamp|datetime|created|updated|modified)", re.IGNORECASE)
    date_only = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    for eq in list(ast.find_all(exp.EQ)):
        col, lit = eq.this, eq.expression
        if not isinstance(col, exp.Column):
            col, lit = lit, eq.this
        if not (isinstance(col, exp.Column) and isinstance(lit, exp.Literal)):
            continue
        if not ts_name.search(col.name) or not date_only.match(str(lit.this)):
            continue

        d = date.fromisoformat(str(lit.this))
        next_d = (d + timedelta(days=1)).isoformat()
        before = eq.sql()
        rng = exp.And(
            this=exp.GTE(this=col.copy(), expression=exp.Literal.string(d.isoformat())),
            expression=exp.LT(this=col.copy(), expression=exp.Literal.string(next_d)),
        )
        eq.replace(exp.Paren(this=rng))
        repairs.append(Repair(
            rule="timestamp_equality",
            description="timestamp = date-literal matches only midnight -> half-open range",
            before_fragment=before,
            after_fragment=rng.sql(),
        ))
    return ast


def _fix_neq_null_drop(ast: exp.Expression, repairs: list[Repair]) -> exp.Expression:
    """`col != 'x'` silently drops NULL rows -> `(col != 'x' OR col IS NULL)`.

    Applied only when no IS NULL/IS NOT NULL guard already references the column.
    """
    guarded: set[str] = set()
    for is_node in ast.find_all(exp.Is):
        if isinstance(is_node.this, exp.Column):
            guarded.add(is_node.this.sql())

    for neq in list(ast.find_all(exp.NEQ)):
        col = neq.this
        if not isinstance(col, exp.Column) or col.sql() in guarded:
            continue
        before = neq.sql()
        fixed = exp.Paren(this=exp.Or(
            this=neq.copy(),
            expression=exp.Is(this=col.copy(), expression=exp.Null()),
        ))
        neq.replace(fixed)
        repairs.append(Repair(
            rule="neq_null_drop",
            description="!= silently drops NULL rows -> OR col IS NULL added",
            before_fragment=before,
            after_fragment=fixed.sql(),
        ))
    return ast


_TRANSFORMS = (_fix_not_in_null, _fix_timestamp_equality, _fix_neq_null_drop)


def repair_sql(sql: str, dialect: str = "duckdb") -> tuple[str, list[Repair]]:
    """Apply all deterministic repairs once. Returns (new_sql, repairs_applied)."""
    try:
        ast = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return sql, []
    repairs: list[Repair] = []
    for transform in _TRANSFORMS:
        ast = transform(ast, repairs)
    return (ast.sql(dialect=dialect), repairs) if repairs else (sql, [])


def verify_and_repair(
    sql: str,
    question: str | None = None,
    dialect: str = "duckdb",
    connector: Any = None,
    policy: Any = None,
    max_rounds: int = 3,
) -> RepairResult:
    """The autonomous loop: verify -> repair -> re-verify until clean or escalation.

    Designed for agent pipelines: the common deterministic bugs are fixed without
    any human or LLM in the loop; only genuinely ambiguous queries escalate.
    """
    result = RepairResult(original_sql=sql, final_sql=sql)
    current = sql

    for round_no in range(1, max_rounds + 1):
        result.rounds = round_no
        report = verify(current, question=question, dialect=dialect,
                        connector=connector, policy=policy)
        result.final_report = report

        if not report.has_blocking() and not report.suggested_review:
            result.final_sql = current
            result.verified = True
            return result

        new_sql, repairs = repair_sql(current, dialect)
        if not repairs:
            break  # nothing deterministic left to fix
        result.repairs.extend(repairs)
        current = new_sql

    # final state after last repair attempt
    report = verify(current, question=question, dialect=dialect,
                    connector=connector, policy=policy)
    result.final_report = report
    result.final_sql = current
    result.verified = not report.has_blocking() and not report.suggested_review
    result.escalate = not result.verified
    return result
