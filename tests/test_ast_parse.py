from verisql import verify


def test_valid_sql_parses_clean():
    r = verify("SELECT 1 AS x", dialect="duckdb")
    assert not any(f.check == "ast_parse" for f in r.flags)
    assert r.confidence > 0.9


def test_garbage_sql_flagged_critical():
    # sqlglot accepts mangled keywords as identifiers; use a structurally invalid statement.
    r = verify("SELECT * FROM", dialect="duckdb")
    assert r.has_blocking()
    assert any(f.check == "ast_parse" and f.severity.value == "critical" for f in r.flags)
