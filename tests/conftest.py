import pytest

try:
    import duckdb  # noqa
    HAVE_DUCKDB = True
except ImportError:
    HAVE_DUCKDB = False


@pytest.fixture
def duckdb_with_schema():
    """In-memory DuckDB with a small schema for tests."""
    if not HAVE_DUCKDB:
        pytest.skip("duckdb not installed")
    from verisql.connectors.duckdb_conn import DuckDBConnector
    import duckdb as dd
    conn = dd.connect(":memory:")
    conn.execute("""
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name VARCHAR,
            email VARCHAR,
            created_at TIMESTAMP
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            amount DECIMAL(10,2),
            status VARCHAR,
            created_at TIMESTAMP
        );
        INSERT INTO customers VALUES
            (1, 'Alice', 'a@x.com', '2026-01-15'),
            (2, 'Bob', NULL, '2026-02-01'),
            (3, 'Carol', 'c@x.com', '2026-03-10');
        INSERT INTO orders VALUES
            (1, 1, 100.00, 'paid', '2026-05-01'),
            (2, 1, 50.00, 'refunded', '2026-05-15'),
            (3, 2, 200.00, 'paid', '2026-06-01');
    """)
    return DuckDBConnector(conn)
