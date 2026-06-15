"""verisql-agent (Bet A): a thin agent runtime where verification is the loop.

The agent harness for code (Cursor, Claude Code) succeeds because every step
runs the compiler/tests and rolls back on failure. This module is the same
pattern for SQL: a generator produces a candidate query, the oracle verifies,
auto-repair attempts the deterministic fixes, optionally the generator gets
the diagnosis and tries again. Loop exits on verified result or budget.

This is not yet "Cursor for data" — that needs schema indexing, plan-mode UI,
multi-step chaining. This is the minimal runtime that proves the pattern:
oracle inside the loop, not after it.

Usage:

    from verisql.agent import run_verified

    def my_generator(question, schema_hint, diagnosis):
        # call any LLM here, or read from a static plan
        return llm.complete(prompt=...)

    result = run_verified(
        question="paid revenue in May 2026",
        generator=my_generator,
        connector=db,
        max_attempts=3,
    )
    print(result.final_sql, result.verified, result.attempts)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from verisql.repair import verify_and_repair


@dataclass
class Attempt:
    sql: str
    verdict: str
    diagnosis: list[dict]


@dataclass
class AgentResult:
    final_sql: str
    verified: bool
    attempts: list[Attempt] = field(default_factory=list)
    final_rows: list[tuple] | None = None
    escalated_reason: str | None = None


Generator = Callable[[str, str, list[dict]], str]
"""(question, schema_hint, diagnosis_from_last_attempt) -> SQL string."""


def _schema_hint(connector: Any) -> str:
    if connector is None or not hasattr(connector, "list_tables"):
        return ""
    parts: list[str] = []
    for t in connector.list_tables()[:20]:
        try:
            cols = connector.list_columns(t)
        except Exception:
            continue
        parts.append(f"{t}({', '.join(cols[:12])})")
    return "; ".join(parts)


def run_verified(
    question: str,
    generator: Generator,
    connector: Any,
    dialect: str = "duckdb",
    max_attempts: int = 3,
    policy: Any = None,
) -> AgentResult:
    schema = _schema_hint(connector)
    diagnosis: list[dict] = []
    result = AgentResult(final_sql="", verified=False)

    for _ in range(max_attempts):
        sql = generator(question, schema, diagnosis)
        repair = verify_and_repair(sql, question=question, dialect=dialect,
                                   connector=connector, policy=policy)
        rep = repair.final_report
        diagnosis = (
            [{"check": f.check, "severity": f.severity.value, "message": f.message}
             for f in rep.flags] if rep else []
        )
        result.attempts.append(Attempt(
            sql=repair.final_sql,
            verdict="verified" if repair.verified else "needs_correction",
            diagnosis=diagnosis,
        ))
        if repair.verified:
            try:
                result.final_rows = connector.execute_readonly(repair.final_sql)
            except Exception as e:
                result.escalated_reason = f"execution failed after verification: {e}"
                break
            result.final_sql = repair.final_sql
            result.verified = True
            return result

    if result.attempts:
        result.final_sql = result.attempts[-1].sql
    result.escalated_reason = result.escalated_reason or "exceeded max_attempts without verification"
    return result
