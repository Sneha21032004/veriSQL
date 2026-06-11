from verisql import repair_sql, verify_and_repair


def test_not_in_null_literal_removed():
    new_sql, repairs = repair_sql("SELECT * FROM customers WHERE id NOT IN (1, NULL, 2)")
    assert any(r.rule == "not_in_null_literal" for r in repairs)
    assert "NULL" not in new_sql.upper()  # NULL literal gone from the IN list


def test_not_in_subquery_guarded():
    new_sql, repairs = repair_sql(
        "SELECT * FROM customers WHERE region NOT IN (SELECT banned FROM blocklist)"
    )
    assert any(r.rule == "not_in_null_subquery" for r in repairs)
    # sqlglot renders the guard as either `x IS NOT NULL` or `NOT x IS NULL`
    upper = new_sql.upper()
    assert "IS NOT NULL" in upper or "NOT BANNED IS NULL" in upper


def test_timestamp_equality_becomes_range():
    new_sql, repairs = repair_sql(
        "SELECT * FROM orders WHERE created_at = '2026-05-01'"
    )
    assert any(r.rule == "timestamp_equality" for r in repairs)
    assert "'2026-05-01'" in new_sql and "'2026-05-02'" in new_sql
    assert ">=" in new_sql and "<" in new_sql


def test_neq_gets_null_guard():
    new_sql, repairs = repair_sql("SELECT * FROM customers WHERE email != 'a@x.com'")
    assert any(r.rule == "neq_null_drop" for r in repairs)
    assert "IS NULL" in new_sql.upper()


def test_neq_already_guarded_untouched():
    sql = "SELECT * FROM customers WHERE email != 'a@x.com' OR email IS NULL"
    _, repairs = repair_sql(sql)
    assert not any(r.rule == "neq_null_drop" for r in repairs)


def test_clean_sql_untouched():
    sql = "SELECT id, name FROM customers WHERE id = 1"
    new_sql, repairs = repair_sql(sql)
    assert new_sql == sql and not repairs


def test_loop_repairs_and_verifies(duckdb_with_schema):
    """The flagship demo: broken NOT-IN-NULL query goes in, verified SQL comes out,
    correct rows return — zero humans, zero LLM tokens."""
    result = verify_and_repair(
        "SELECT * FROM customers WHERE id NOT IN (99, NULL)",
        dialect="duckdb",
        connector=duckdb_with_schema,
    )
    assert result.repairs, result.summary()
    assert result.verified, result.summary()
    rows = duckdb_with_schema.execute_readonly(result.final_sql)
    assert len(rows) == 3  # original returned 0 rows; repaired returns all customers


def test_loop_escalates_when_unfixable(duckdb_with_schema):
    # cartesian product has no safe deterministic repair without FK metadata
    result = verify_and_repair(
        "SELECT * FROM customers, orders",
        dialect="duckdb",
        connector=duckdb_with_schema,
    )
    assert result.escalate
    assert not result.verified
