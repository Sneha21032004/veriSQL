"""MCP tool functions tested directly — the same callables FastMCP exposes."""
import pytest

pytest.importorskip("mcp")

from verisql import mcp_server


def test_verify_sql_clean():
    out = mcp_server.verify_sql("SELECT 1 AS x")
    assert out["verdict"] == "verified"
    assert out["confidence"] >= 0.9


def test_verify_sql_flags_silent_failure():
    out = mcp_server.verify_sql(
        "SELECT SUM(amount) FROM orders WHERE status = 'paid'",
        question="total revenue last month",
    )
    assert out["verdict"] in ("needs_correction", "rejected")
    assert any(d["check"] == "date_coverage" for d in out["diagnosis"])


def test_fix_sql_repairs_not_in_null():
    out = mcp_server.fix_sql("SELECT * FROM customers WHERE id NOT IN (1, NULL)")
    assert out["repairs_applied"], out
    assert "NULL" not in out["final_sql"].upper()
    assert out["verdict"] == "verified"


def test_fix_sql_repairs_timestamp_equality():
    out = mcp_server.fix_sql("SELECT * FROM orders WHERE created_at = '2026-05-01'")
    rules = {r["rule"] for r in out["repairs_applied"]}
    assert "timestamp_equality" in rules
    assert "'2026-05-02'" in out["final_sql"]


def test_diff_sql_catches_dropped_filter():
    out = mcp_server.diff_sql(
        "SELECT id FROM orders WHERE status='paid' AND amount > 100",
        "SELECT id FROM orders WHERE status='paid'",
    )
    assert out["verdict"] in ("not_equivalent", "likely_not_equivalent")
    assert any(d["kind"] == "filter" for d in out["differences"])


def test_tools_registered():
    # FastMCP must expose exactly our three tools
    import anyio
    tools = anyio.run(mcp_server.mcp.list_tools)
    names = {t.name for t in tools}
    assert names == {"verify_sql", "fix_sql", "diff_sql"}
    # every tool needs a docstring-derived description for the agent
    assert all(t.description for t in tools)
