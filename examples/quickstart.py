"""Quickstart: drop verisql in front of any text-to-SQL output."""
import duckdb
from verisql import verify
from verisql.connectors.duckdb_conn import DuckDBConnector


def main() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE customers (id INT, name VARCHAR, email VARCHAR);
        CREATE TABLE orders (id INT, customer_id INT, amount DECIMAL, status VARCHAR, created_at DATE);
        INSERT INTO customers VALUES (1, 'Alice', 'a@x.com'), (2, 'Bob', NULL);
        INSERT INTO orders VALUES
          (1, 1, 100, 'paid',     '2026-05-01'),
          (2, 1, 50,  'refunded', '2026-05-15'),
          (3, 2, 200, 'paid',     '2026-06-01');
    """)
    db = DuckDBConnector(conn)

    cases: list[tuple[str, str]] = [
        ("What was total revenue last month?",
         "SELECT SUM(amount) FROM orders WHERE status = 'paid'"),
        ("How many customers have not ordered?",
         "SELECT COUNT(*) FROM customers WHERE id NOT IN (SELECT customer_id FROM orders)"),
        ("Show me all orders and customers",
         "SELECT * FROM orders, customers"),
        ("Total paid revenue in May 2026",
         "SELECT SUM(amount) FROM orders WHERE status = 'paid' AND created_at >= '2026-05-01' AND created_at < '2026-06-01'"),
    ]

    for question, sql in cases:
        print("=" * 72)
        print(f"Q: {question}")
        print(f"SQL: {sql}")
        report = verify(sql, question=question, dialect="duckdb", connector=db)
        print(report.summary())
        print()


if __name__ == "__main__":
    main()
