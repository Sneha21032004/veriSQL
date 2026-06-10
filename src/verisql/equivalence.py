"""Semantic equivalence verification for SQL migrations.

Use case: a bank migrates Teradata/Oracle -> Snowflake/Databricks and uses an LLM
to translate thousands of legacy queries. The sign-off question is: "does the
translated SQL produce the same answer?" No reviewer can eyeball 4,000 procs.

Two independent signals, cheapest first:

1. Structural diff (free, no DB): normalize both ASTs via sqlglot, compare
   projections, filters, joins, grouping. Catches dropped predicates, changed
   join types, silently renamed output columns.

2. Result diff (read-only execution): run both against the same data (or the
   new warehouse after backfill), compare row counts, column shapes, and content
   hashes order-insensitively. Ground truth on real data.

Output: EquivalenceReport with verdict equivalent | likely_equivalent |
not_equivalent | unknown — designed to rank thousands of translations so humans
review only the risky ones.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import expressions as exp


@dataclass
class Difference:
    kind: str        # projection | filter | join | grouping | rowcount | data | parse
    severity: str    # fatal | major | minor
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EquivalenceReport:
    old_sql: str
    new_sql: str
    old_dialect: str
    new_dialect: str
    differences: list[Difference] = field(default_factory=list)
    executed: bool = False
    verdict: str = "unknown"

    def add(self, diff: Difference) -> None:
        self.differences.append(diff)

    def finalize(self) -> "EquivalenceReport":
        fatals = [d for d in self.differences if d.severity == "fatal"]
        majors = [d for d in self.differences if d.severity == "major"]
        if fatals:
            self.verdict = "not_equivalent"
        elif majors:
            self.verdict = "not_equivalent" if self.executed else "likely_not_equivalent"
        elif self.executed:
            self.verdict = "equivalent"
        else:
            self.verdict = "likely_equivalent"
        return self

    def summary(self) -> str:
        lines = [
            f"Equivalence verdict: {self.verdict.upper()}",
            f"  structural+data differences: {len(self.differences)}",
            f"  executed against data: {self.executed}",
        ]
        for d in self.differences:
            lines.append(f"  [{d.severity.upper()}] {d.kind}: {d.message}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# structural comparison
# --------------------------------------------------------------------------- #

def _parse(sql: str, dialect: str) -> exp.Expression | None:
    try:
        return sqlglot.parse_one(sql, read=dialect, error_level=sqlglot.ErrorLevel.IMMEDIATE)
    except Exception:
        return None


def _projection_names(ast: exp.Expression) -> list[str]:
    sel = ast.find(exp.Select)
    if sel is None:
        return []
    return [p.alias_or_name.lower() for p in sel.expressions]


def _normalized_where(ast: exp.Expression, dialect: str) -> str | None:
    sel = ast.find(exp.Select)
    if sel is None:
        return None
    where = sel.args.get("where")
    if where is None:
        return None
    # normalize through generic SQL rendering for cross-dialect comparison
    return where.this.sql(dialect="duckdb", normalize=True)


def _join_signature(ast: exp.Expression) -> list[tuple[str, str]]:
    sigs = []
    for j in ast.find_all(exp.Join):
        kind = (j.side or j.kind or "INNER").upper()
        tbl = j.this.name.lower() if isinstance(j.this, exp.Table) else "<derived>"
        sigs.append((kind, tbl))
    return sorted(sigs)


def _group_by_signature(ast: exp.Expression) -> list[str]:
    sel = ast.find(exp.Select)
    if sel is None:
        return []
    group = sel.args.get("group")
    if group is None:
        return []
    return sorted(g.sql(dialect="duckdb").lower() for g in group.expressions)


def compare_structure(report: EquivalenceReport) -> None:
    old_ast = _parse(report.old_sql, report.old_dialect)
    new_ast = _parse(report.new_sql, report.new_dialect)

    if old_ast is None or new_ast is None:
        which = "old" if old_ast is None else "new"
        report.add(Difference("parse", "fatal", f"{which} SQL failed to parse"))
        return

    old_proj, new_proj = _projection_names(old_ast), _projection_names(new_ast)
    if old_proj != new_proj:
        sev = "major" if set(old_proj) != set(new_proj) else "minor"  # order-only = minor
        report.add(Difference(
            "projection", sev,
            f"output columns differ: {old_proj} vs {new_proj}",
            {"old": old_proj, "new": new_proj},
        ))

    old_where = _normalized_where(old_ast, report.old_dialect)
    new_where = _normalized_where(new_ast, report.new_dialect)
    if (old_where or "") != (new_where or ""):
        report.add(Difference(
            "filter", "major",
            "WHERE clauses are not structurally identical after normalization",
            {"old": old_where, "new": new_where},
        ))

    if _join_signature(old_ast) != _join_signature(new_ast):
        report.add(Difference(
            "join", "major",
            f"join structure differs: {_join_signature(old_ast)} vs {_join_signature(new_ast)}",
        ))

    if _group_by_signature(old_ast) != _group_by_signature(new_ast):
        report.add(Difference(
            "grouping", "major",
            f"GROUP BY differs: {_group_by_signature(old_ast)} vs {_group_by_signature(new_ast)}",
        ))


# --------------------------------------------------------------------------- #
# result comparison (read-only execution)
# --------------------------------------------------------------------------- #

def _result_fingerprint(rows: list[tuple]) -> str:
    """Order-insensitive content hash of a result set."""
    row_hashes = sorted(
        hashlib.sha256(repr(tuple(str(v) for v in row)).encode()).hexdigest()
        for row in rows
    )
    return hashlib.sha256("".join(row_hashes).encode()).hexdigest()


def compare_results(
    report: EquivalenceReport,
    old_connector: Any,
    new_connector: Any | None = None,
    sample_rows: int = 1000,
) -> None:
    """Execute both statements read-only and diff the result sets.

    new_connector defaults to old_connector (same database, e.g. validating a
    rewritten query against the same warehouse).
    """
    new_connector = new_connector or old_connector
    try:
        old_rows = old_connector.execute_readonly(report.old_sql, max_rows=sample_rows)
        new_rows = new_connector.execute_readonly(report.new_sql, max_rows=sample_rows)
    except Exception as e:
        report.add(Difference("data", "fatal", f"execution failed: {e}"))
        return

    report.executed = True

    if len(old_rows) != len(new_rows):
        report.add(Difference(
            "rowcount", "major",
            f"row counts differ: {len(old_rows)} vs {len(new_rows)}",
            {"old": len(old_rows), "new": len(new_rows)},
        ))
        return

    if old_rows and len(old_rows[0]) != len(new_rows[0]):
        report.add(Difference(
            "data", "major",
            f"column counts differ: {len(old_rows[0])} vs {len(new_rows[0])}",
        ))
        return

    if _result_fingerprint(old_rows) != _result_fingerprint(new_rows):
        report.add(Difference(
            "data", "major",
            "result content differs (order-insensitive hash mismatch)",
        ))


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #

def verify_equivalence(
    old_sql: str,
    new_sql: str,
    old_dialect: str = "duckdb",
    new_dialect: str | None = None,
    connector: Any = None,
    new_connector: Any = None,
    sample_rows: int = 1000,
) -> EquivalenceReport:
    """Compare a legacy query and its (LLM-)translated replacement.

    Structural diff always runs (free). Result diff runs when a connector is
    provided. Designed for bulk-ranking migration batches: sort by verdict and
    review only not_equivalent / likely_not_equivalent items.
    """
    report = EquivalenceReport(
        old_sql=old_sql,
        new_sql=new_sql,
        old_dialect=old_dialect,
        new_dialect=new_dialect or old_dialect,
    )
    compare_structure(report)
    has_fatal = any(d.severity == "fatal" for d in report.differences)
    if connector is not None and not has_fatal:
        compare_results(report, connector, new_connector, sample_rows)
    return report.finalize()
