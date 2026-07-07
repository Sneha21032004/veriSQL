"""Shared verify/fix payload builders.

Every integration surface (OpenAI function calling, LangChain, LlamaIndex)
returns these exact payload shapes — identical to the MCP server's responses —
so an agent switching frameworks never re-learns the oracle's output format.
"""
from __future__ import annotations

from typing import Any

from verisql.repair import verify_and_repair
from verisql.verify import verify


def _flags_payload(report: Any) -> list[dict[str, Any]]:
    return [
        {"check": f.check, "severity": f.severity.value, "message": f.message}
        for f in report.flags
    ]


def verify_payload(
    sql: str,
    question: str = "",
    dialect: str = "duckdb",
    connector: Any = None,
    policy: Any = None,
) -> dict[str, Any]:
    """Run deterministic verification and return the JSON-safe verdict."""
    report = verify(sql, question=question or None, dialect=dialect,
                    connector=connector, policy=policy)
    if report.has_blocking():
        verdict = "rejected"
    elif report.suggested_review:
        verdict = "needs_correction"
    else:
        verdict = "verified"
    return {
        "verdict": verdict,
        "confidence": round(report.confidence, 2),
        "diagnosis": _flags_payload(report),
        "executed_against_db": report.executed,
        "row_count": report.row_count,
    }


def fix_payload(
    sql: str,
    question: str = "",
    dialect: str = "duckdb",
    connector: Any = None,
    policy: Any = None,
) -> dict[str, Any]:
    """Verify, auto-repair, re-verify; return the corrected SQL and audit trail."""
    result = verify_and_repair(sql, question=question or None, dialect=dialect,
                               connector=connector, policy=policy)
    payload: dict[str, Any] = {
        "verdict": "verified" if result.verified else "needs_correction",
        "final_sql": result.final_sql,
        "repairs_applied": [
            {"rule": r.rule, "description": r.description,
             "before": r.before_fragment, "after": r.after_fragment}
            for r in result.repairs
        ],
        "rounds": result.rounds,
    }
    if result.final_report is not None:
        payload["remaining_diagnosis"] = _flags_payload(result.final_report)
        payload["confidence"] = round(result.final_report.confidence, 2)
    return payload
