from verisql import verify


def test_cartesian_no_join_predicate_flagged():
    sql = "SELECT * FROM customers c, orders o"
    r = verify(sql, dialect="duckdb")
    assert any(f.check == "cartesian_join" and f.severity.value == "critical" for f in r.flags)


def test_explicit_join_predicate_passes():
    sql = "SELECT * FROM customers c, orders o WHERE c.id = o.customer_id"
    r = verify(sql, dialect="duckdb")
    assert not any(f.check == "cartesian_join" for f in r.flags)


def test_ansi_join_passes():
    sql = "SELECT * FROM customers c JOIN orders o ON c.id = o.customer_id"
    r = verify(sql, dialect="duckdb")
    assert not any(f.check == "cartesian_join" for f in r.flags)
