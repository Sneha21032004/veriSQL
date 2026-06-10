from verisql import verify


def test_orders_without_where_flagged():
    r = verify("SELECT * FROM orders", dialect="duckdb")
    assert any(f.check == "filter_required" for f in r.flags)


def test_orders_with_where_passes():
    r = verify("SELECT * FROM orders WHERE status = 'paid'", dialect="duckdb")
    assert not any(f.check == "filter_required" for f in r.flags)


def test_orders_with_limit_passes():
    r = verify("SELECT * FROM orders LIMIT 100", dialect="duckdb")
    assert not any(f.check == "filter_required" for f in r.flags)
