"""Parse-path checks work for every dialect with zero connector and zero driver."""
import pytest
from verisql import verify


@pytest.mark.parametrize("dialect", ["duckdb", "postgres", "snowflake", "bigquery", "mysql", "tsql"])
def test_valid_sql_parses_per_dialect(dialect):
    r = verify("SELECT id, name FROM customers WHERE id = 1", dialect=dialect)
    assert not r.has_blocking()


@pytest.mark.parametrize("dialect", ["snowflake", "bigquery"])
def test_cartesian_caught_per_dialect(dialect):
    r = verify("SELECT * FROM a, b", dialect=dialect)
    assert any(f.check == "cartesian_join" for f in r.flags)


def test_snowflake_specific_syntax():
    # QUALIFY is Snowflake/BigQuery specific — must parse cleanly
    sql = (
        "SELECT id, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC) AS rn "
        "FROM orders QUALIFY rn = 1"
    )
    r = verify(sql, dialect="snowflake")
    assert not r.has_blocking()


def test_bigquery_backtick_identifiers():
    r = verify("SELECT `user id` FROM `project.dataset.events` WHERE `user id` = 5", dialect="bigquery")
    assert not r.has_blocking()


def test_connector_import_guards():
    """Optional-driver connectors must raise a clear install hint, not a bare ImportError."""
    import importlib
    for mod, extra in [
        ("verisql.connectors.snowflake_conn", "snowflake"),
        ("verisql.connectors.bigquery_conn", "bigquery"),
        ("verisql.connectors.postgres_conn", "postgres"),
    ]:
        try:
            importlib.import_module(mod)
        except ImportError as e:
            assert extra in str(e), f"{mod} import hint should mention '{extra}'"
