from verisql import verify, Policy


def test_invariant_violation_flagged(duckdb_with_schema):
    # orders has a refunded row with amount 50; force a negative-revenue style invariant
    policy = Policy(invariants=["amount >= 100"])
    r = verify(
        "SELECT amount FROM orders",
        dialect="duckdb",
        connector=duckdb_with_schema,
        policy=policy,
    )
    # row with amount=50 violates amount>=100
    assert any(f.check == "business_invariant" and f.severity.value == "critical" for f in r.flags)


def test_invariant_satisfied_no_flag(duckdb_with_schema):
    policy = Policy(invariants=["amount >= 0"])
    r = verify(
        "SELECT amount FROM orders",
        dialect="duckdb",
        connector=duckdb_with_schema,
        policy=policy,
    )
    assert not any(f.check == "business_invariant" for f in r.flags)


def test_required_filter_missing_flagged(duckdb_with_schema):
    policy = Policy(required_filters={"orders": ["created_at"]})
    r = verify(
        "SELECT SUM(amount) AS total FROM orders WHERE status = 'paid'",
        dialect="duckdb",
        connector=duckdb_with_schema,
        policy=policy,
    )
    assert any(f.check == "required_filter" for f in r.flags)


def test_required_filter_present_passes(duckdb_with_schema):
    policy = Policy(required_filters={"orders": ["created_at"]})
    r = verify(
        "SELECT SUM(amount) AS total FROM orders WHERE created_at >= '2026-05-01'",
        dialect="duckdb",
        connector=duckdb_with_schema,
        policy=policy,
    )
    assert not any(f.check == "required_filter" for f in r.flags)


def test_result_set_executed_once(duckdb_with_schema):
    """Invariant check must reuse zero_row's cached result, not re-execute."""
    calls = {"n": 0}
    orig = duckdb_with_schema.execute_readonly

    def counting(sql, max_rows=100):
        calls["n"] += 1
        return orig(sql, max_rows)

    duckdb_with_schema.execute_readonly = counting  # type: ignore[method-assign]
    policy = Policy(invariants=["amount >= 0"])
    verify("SELECT amount FROM orders", dialect="duckdb",
           connector=duckdb_with_schema, policy=policy)
    assert calls["n"] == 1, f"expected single execution, got {calls['n']}"
