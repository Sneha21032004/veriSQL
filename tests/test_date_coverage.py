from verisql import verify


def test_question_mentions_date_but_sql_lacks_filter():
    r = verify(
        sql="SELECT SUM(amount) FROM orders WHERE status = 'paid'",
        question="What was total revenue last month?",
        dialect="duckdb",
    )
    assert any(f.check == "date_coverage" for f in r.flags)


def test_question_mentions_date_and_sql_filters_date():
    r = verify(
        sql="SELECT SUM(amount) FROM orders WHERE created_at >= '2026-05-01' AND status = 'paid'",
        question="What was total revenue last month?",
        dialect="duckdb",
    )
    assert not any(f.check == "date_coverage" for f in r.flags)


def test_no_time_question_no_flag():
    r = verify(
        sql="SELECT SUM(amount) FROM orders WHERE status = 'paid'",
        question="What is the total revenue from paid orders?",
        dialect="duckdb",
    )
    assert not any(f.check == "date_coverage" for f in r.flags)
