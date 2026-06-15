"""Tests for the multi-bet additions: YAML repair rules, history learner,
agent runtime, and Postgres extension SQL (smoke-checked via file presence)."""
from pathlib import Path

import pytest

from verisql import (
    YamlRule, apply_rules,
    QueryHistory,
    run_verified,
)


# ---- Bet 2: YAML repair rules --------------------------------------------

def test_yaml_rule_function_swap():
    rules = [YamlRule(
        name="utcnow_to_currentts",
        description="prefer CURRENT_TIMESTAMP over UTC_NOW",
        match={"kind": "function", "name": "utc_now"},
        replace={"sql": "CURRENT_TIMESTAMP"},
    )]
    new_sql, repairs = apply_rules("SELECT UTC_NOW() AS now", rules)
    assert repairs and repairs[0].rule == "utcnow_to_currentts"
    assert "CURRENT_TIMESTAMP" in new_sql.upper()


def test_yaml_rule_misses_unrelated_sql():
    rules = [YamlRule(
        name="x", description="", match={"kind": "function", "name": "utc_now"},
        replace={"sql": "CURRENT_TIMESTAMP"},
    )]
    _, repairs = apply_rules("SELECT NOW()", rules)
    assert not repairs


# ---- Bet 4: query-history learner ----------------------------------------

def test_history_baseline_then_drift(duckdb_with_schema, tmp_path):
    hist = QueryHistory(tmp_path / "h.db")
    sql = "SELECT * FROM customers"
    r1 = hist.check(sql, "all_customers", duckdb_with_schema)
    assert r1.severity == "info"   # baseline

    # second look at the same data: should be within distribution
    r2 = hist.check(sql, "all_customers", duckdb_with_schema)
    assert r2.severity == "none"


def test_history_step_change_detected(duckdb_with_schema, tmp_path):
    """A baseline of ~1 row, then a query returning many rows, should trip the
    >5x step-change guard."""
    hist = QueryHistory(tmp_path / "h.db")
    baseline_sql = "SELECT * FROM customers WHERE id = 1"   # 1 row
    for _ in range(5):
        hist.record(baseline_sql, "single", duckdb_with_schema)
    out = hist.check("SELECT id FROM customers", "single", duckdb_with_schema)  # 3 rows
    # 3 vs 1 ratio = 3x, not >5x, but stddev is 0 so sigma rule won't fire either.
    # Bump the contrast to make it deterministic.
    for _ in range(5):
        hist.record(baseline_sql, "bigchange", duckdb_with_schema)
    big = hist.check("SELECT c.id FROM customers c CROSS JOIN orders o "
                     "WHERE 1=1", "bigchange", duckdb_with_schema)  # 3*3 = 9 rows
    assert big.severity in ("warn", "error"), big
    hist.close()


# ---- Bet A: agent runtime ------------------------------------------------

def test_agent_self_corrects(duckdb_with_schema):
    """Generator emits a broken NOT IN NULL query; the oracle repairs it
    inside the loop and the verified SQL ships."""
    def gen(question, schema_hint, diagnosis):
        return "SELECT name FROM customers WHERE id NOT IN (99, NULL)"

    result = run_verified(
        question="Which customers are NOT id 99?",
        generator=gen,
        connector=duckdb_with_schema,
        max_attempts=2,
    )
    assert result.verified, result.escalated_reason
    assert result.final_rows is not None
    assert len(result.final_rows) == 3   # repaired query returns all three customers
    assert result.attempts and result.attempts[-1].verdict == "verified"


def test_agent_escalates_when_generator_keeps_failing(duckdb_with_schema):
    def bad_gen(q, s, d):
        return "SELECT * FROM customers, orders"   # cartesian, unfixable

    result = run_verified("anything", bad_gen, duckdb_with_schema, max_attempts=2)
    assert not result.verified
    assert "max_attempts" in (result.escalated_reason or "")


# ---- Bet 6: Postgres extension files present and well-formed --------------

def test_postgres_extension_artifacts():
    root = Path(__file__).resolve().parent.parent / "postgres-extension"
    control = (root / "verisql.control").read_text(encoding="utf-8")
    assert "default_version = '0.1.0'" in control
    sql = (root / "verisql--0.1.0.sql").read_text(encoding="utf-8")
    # the five public function names must exist
    for fn in ("verisql.check", "verisql.explain_sanity", "verisql.fingerprint",
               "verisql.diff", "verisql.history_check"):
        assert fn in sql, f"missing function {fn}"
    # mutation guard must reject every dangerous keyword we promise to block
    for kw in ("insert", "update", "delete", "drop", "alter", "truncate", "create"):
        assert kw in sql.lower()
