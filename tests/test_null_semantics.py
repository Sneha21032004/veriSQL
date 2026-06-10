from verisql import verify


def test_neq_without_null_guard_flagged():
    sql = "SELECT * FROM customers WHERE email != 'a@x.com'"
    r = verify(sql, dialect="duckdb")
    assert any(f.check == "null_semantics" for f in r.flags)


def test_neq_with_null_guard_passes():
    sql = "SELECT * FROM customers WHERE email != 'a@x.com' OR email IS NULL"
    r = verify(sql, dialect="duckdb")
    assert not any(f.check == "null_semantics" for f in r.flags)


def test_not_in_flagged():
    sql = "SELECT * FROM customers WHERE id NOT IN (1, 2)"
    r = verify(sql, dialect="duckdb")
    assert any(f.check == "null_semantics" for f in r.flags)
