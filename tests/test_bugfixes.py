"""Regression tests for real-world bugs found in self-audit."""
import pytest

from verisql import verify
from verisql.connectors.base import ensure_limited, guard_mutation


# Bug 1: CTE names were flagged as hallucinated tables -------------------------

def test_cte_not_flagged_as_missing_table(duckdb_with_schema):
    sql = (
        "WITH recent AS (SELECT * FROM orders WHERE created_at >= '2026-05-01') "
        "SELECT COUNT(*) FROM recent"
    )
    r = verify(sql, dialect="duckdb", connector=duckdb_with_schema)
    assert not any(f.check == "schema_existence" for f in r.flags), r.summary()


def test_real_missing_table_still_flagged(duckdb_with_schema):
    sql = "WITH recent AS (SELECT * FROM orders) SELECT * FROM ghost_table"
    r = verify(sql, dialect="duckdb", connector=duckdb_with_schema)
    assert any(f.check == "schema_existence" for f in r.flags)


# Bug 2: mutation guard bypassed by leading comments ---------------------------

@pytest.mark.parametrize("sql", [
    "-- innocent comment\nDELETE FROM customers",
    "/* block */ DROP TABLE customers",
    "  \n-- a\n-- b\nUPDATE customers SET name = 'x'",
    "DELETE FROM customers",
    "INSERT INTO customers VALUES (9, 'evil', NULL, NULL)",
])
def test_guard_blocks_mutations_with_comment_prefixes(sql):
    with pytest.raises(PermissionError):
        guard_mutation(sql, "duckdb")


def test_guard_allows_selects_with_comments():
    guard_mutation("-- note\nSELECT * FROM customers", "duckdb")  # must not raise
    guard_mutation("/* hint */ WITH x AS (SELECT 1) SELECT * FROM x", "duckdb")


def test_guard_enforced_end_to_end(duckdb_with_schema):
    with pytest.raises(PermissionError):
        duckdb_with_schema.execute_readonly("-- sneaky\nDELETE FROM customers")
    # table unharmed
    rows = duckdb_with_schema.execute_readonly("SELECT COUNT(*) FROM customers")
    assert rows[0][0] == 3


# Bug 3: LIMIT detection missed newline-separated LIMIT ------------------------

def test_ensure_limited_respects_newline_limit():
    sql = "SELECT * FROM orders\nLIMIT 10"
    assert ensure_limited(sql, 100) == sql  # not double-wrapped


def test_ensure_limited_wraps_unlimited():
    out = ensure_limited("SELECT * FROM orders", 100)
    assert "LIMIT 100" in out and "_verisql_sub" in out
