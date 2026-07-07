"""@sql_guard — the framework-free way to put the oracle inside any SQL generator.

Wrap any function that returns SQL. The guard verifies the output, auto-repairs
the deterministic bugs, and either returns provably-checked SQL or raises
`SQLVerificationError` carrying the full diagnosis — ready to feed back into
the generator for a retry.

    @sql_guard(connector=db, question_arg="question")
    def write_sql(question: str) -> str:
        return llm.complete(...)

Zero dependencies beyond VeriSQL itself.
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from verisql.repair import RepairResult, verify_and_repair


class SQLVerificationError(Exception):
    """Raised when generated SQL cannot be verified even after auto-repair."""

    def __init__(self, repair_result: RepairResult):
        self.repair_result = repair_result
        flags = repair_result.final_report.flags if repair_result.final_report else []
        self.diagnosis = [
            {"check": f.check, "severity": f.severity.value, "message": f.message}
            for f in flags
        ]
        messages = "; ".join(d["message"] for d in self.diagnosis) or "verification failed"
        super().__init__(f"SQL failed verification after repair: {messages}")


def sql_guard(
    connector: Any = None,
    dialect: str = "duckdb",
    policy: Any = None,
    question_arg: str | None = None,
    max_rounds: int = 3,
) -> Callable:
    """Decorator: verify-and-repair the SQL returned by the wrapped function.

    Args:
        connector: optional DB adapter for live schema/plan/execution checks.
        dialect: sqlglot dialect of the generated SQL.
        policy: optional Policy with invariants and governance rules.
        question_arg: name of the wrapped function's parameter holding the
            natural-language question — enables intent checks (date coverage).
        max_rounds: repair/re-verify iterations before giving up.

    Returns the verified (possibly repaired) SQL string, or raises
    `SQLVerificationError` with the diagnosis when unfixable.
    """
    def decorator(fn: Callable[..., str]) -> Callable[..., str]:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> str:
            sql = fn(*args, **kwargs)

            question = None
            if question_arg is not None:
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                question = bound.arguments.get(question_arg)

            result = verify_and_repair(
                sql, question=question, dialect=dialect,
                connector=connector, policy=policy, max_rounds=max_rounds,
            )
            if result.verified:
                return result.final_sql
            raise SQLVerificationError(result)

        return wrapper
    return decorator
