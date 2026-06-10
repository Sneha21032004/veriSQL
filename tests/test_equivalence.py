from verisql import verify_equivalence


def test_identical_queries_equivalent_structurally():
    r = verify_equivalence(
        "SELECT id, name FROM customers WHERE id > 5",
        "SELECT id, name FROM customers WHERE id > 5",
    )
    assert r.verdict == "likely_equivalent"
    assert not r.differences


def test_dropped_filter_caught():
    r = verify_equivalence(
        "SELECT id FROM orders WHERE status = 'paid' AND amount > 100",
        "SELECT id FROM orders WHERE status = 'paid'",
    )
    assert any(d.kind == "filter" for d in r.differences)
    assert r.verdict in ("not_equivalent", "likely_not_equivalent")


def test_changed_join_type_caught():
    r = verify_equivalence(
        "SELECT c.name FROM customers c LEFT JOIN orders o ON c.id = o.customer_id",
        "SELECT c.name FROM customers c INNER JOIN orders o ON c.id = o.customer_id",
    )
    assert any(d.kind == "join" for d in r.differences)


def test_renamed_output_column_caught():
    r = verify_equivalence(
        "SELECT SUM(amount) AS revenue FROM orders",
        "SELECT SUM(amount) AS total FROM orders",
    )
    assert any(d.kind == "projection" for d in r.differences)


def test_cross_dialect_normalization():
    # Same logic, different dialects — should structurally match
    r = verify_equivalence(
        "SELECT id, name FROM customers WHERE id > 5",
        "SELECT id, name FROM customers WHERE id > 5",
        old_dialect="tsql",
        new_dialect="snowflake",
    )
    assert r.verdict == "likely_equivalent"


def test_result_diff_confirms_equivalence(duckdb_with_schema):
    r = verify_equivalence(
        "SELECT id, name FROM customers WHERE id <= 2",
        "SELECT id, name FROM customers WHERE id < 3",
        connector=duckdb_with_schema,
    )
    # WHERE differs structurally (major) but data agrees; executed comparison ran
    assert r.executed
    data_diffs = [d for d in r.differences if d.kind in ("rowcount", "data")]
    assert not data_diffs


def test_result_diff_catches_wrong_translation(duckdb_with_schema):
    r = verify_equivalence(
        "SELECT id FROM orders WHERE status = 'paid'",
        "SELECT id FROM orders WHERE status = 'refunded'",
        connector=duckdb_with_schema,
    )
    assert r.executed
    assert any(d.kind in ("rowcount", "data") for d in r.differences)
    assert r.verdict == "not_equivalent"
