"""VeriSQL MCP server — the SQL-correctness oracle as a tool any agent can call.

Code agents self-correct because compilers and test suites give deterministic
feedback. SQL has no such oracle — until the agent loads this server. The agent
writes SQL, calls `verify_sql` or `fix_sql`, gets a deterministic verdict plus a
repaired query, and corrects itself. No human gate; the human only sees verified
results (and the audit trail).

Run:
    verisql-mcp                         # stdio transport
    verisql-mcp --duckdb path/to.db     # with live database checks

Register in Claude Code (project .mcp.json or `claude mcp add`):
    { "mcpServers": { "verisql": { "command": "verisql-mcp",
                                   "args": ["--duckdb", "warehouse.duckdb"] } } }
"""
from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from verisql import verify as _verify
from verisql.equivalence import verify_equivalence as _verify_equivalence
from verisql.repair import verify_and_repair as _verify_and_repair

mcp = FastMCP(
    "verisql",
    instructions=(
        "Deterministic verification oracle for SQL. After writing any SQL query, "
        "call fix_sql (preferred) or verify_sql before presenting results. If the "
        "verdict is not 'verified', use the returned diagnosis and repaired SQL to "
        "correct your query, then verify again. These checks are deterministic AST "
        "and execution analysis — trust them over your own judgment of the SQL."
    ),
)

_connector: Any = None  # set in main() when --duckdb is passed


def _get_connector() -> Any:
    return _connector


def _flags_payload(report: Any) -> list[dict[str, Any]]:
    return [
        {"check": f.check, "severity": f.severity.value, "message": f.message}
        for f in report.flags
    ]


@mcp.tool()
def verify_sql(sql: str, question: str = "", dialect: str = "duckdb") -> dict:
    """Verify an SQL query for silent failures (NULL semantics, cartesian joins,
    missing date scope, schema errors, invariant breaches). Returns a deterministic
    verdict, confidence score, and a diagnosis for each problem found.

    Args:
        sql: the SQL query to verify.
        question: the natural-language question the SQL is meant to answer
            (enables intent checks like date-coverage). Optional but recommended.
        dialect: sql dialect — duckdb, postgres, snowflake, bigquery, mysql, tsql.
    """
    report = _verify(sql, question=question or None, dialect=dialect,
                     connector=_get_connector())
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


@mcp.tool()
def fix_sql(sql: str, question: str = "", dialect: str = "duckdb") -> dict:
    """Verify an SQL query AND auto-repair the deterministic bugs (NOT IN with NULL,
    timestamp=date equality, != dropping NULL rows), then re-verify. Returns the
    corrected SQL ready to execute. Prefer this over verify_sql when you intend to
    run the query.

    Args:
        sql: the SQL query to verify and repair.
        question: the natural-language question behind the SQL. Optional.
        dialect: sql dialect — duckdb, postgres, snowflake, bigquery, mysql, tsql.
    """
    result = _verify_and_repair(sql, question=question or None, dialect=dialect,
                                connector=_get_connector())
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


@mcp.tool()
def diff_sql(old_sql: str, new_sql: str, old_dialect: str = "duckdb",
             new_dialect: str = "") -> dict:
    """Check whether two SQL queries are semantically equivalent — use when
    rewriting, translating between dialects, or migrating legacy SQL. Compares
    normalized ASTs (projections, filters, joins, grouping) and, when a database
    is connected, executes both read-only and diffs the results.

    Args:
        old_sql: the original / legacy query.
        new_sql: the rewritten / translated query.
        old_dialect: dialect of the original query.
        new_dialect: dialect of the new query (defaults to old_dialect).
    """
    report = _verify_equivalence(
        old_sql, new_sql, old_dialect=old_dialect,
        new_dialect=new_dialect or None, connector=_get_connector(),
    )
    return {
        "verdict": report.verdict,
        "differences": [
            {"kind": d.kind, "severity": d.severity, "message": d.message}
            for d in report.differences
        ],
        "executed_against_db": report.executed,
    }


def main() -> None:
    global _connector
    parser = argparse.ArgumentParser(description="VeriSQL MCP server (stdio)")
    parser.add_argument("--duckdb", default=os.environ.get("VERISQL_DUCKDB"),
                        help="Path to a DuckDB file for live schema/execution checks.")
    args = parser.parse_args()

    if args.duckdb:
        from verisql.connectors.duckdb_conn import DuckDBConnector
        _connector = DuckDBConnector.from_path(args.duckdb)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
