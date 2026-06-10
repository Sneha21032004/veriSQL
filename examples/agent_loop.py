"""How to wire verisql into a text-to-SQL agent loop.

The verifier sits between SQL generation and execution. Deterministic checks are
free; the LLM critic (if configured) fires only for ambiguous cases. Most queries
are decided without spending a single critic token.
"""
import duckdb
from verisql import verify, Policy
from verisql.connectors.duckdb_conn import DuckDBConnector


def gate(sql: str, question: str, db, policy) -> str:
    """Return 'deliver' | 'review' | 'reject' for an agent-generated query."""
    report = verify(
        sql,
        question=question,
        dialect="duckdb",
        connector=db,
        policy=policy,
        # critic=anthropic_critic(),   # uncomment to enable LLM escalation
    )
    if report.has_blocking():
        return "reject"
    if report.suggested_review:
        return "review"
    return "deliver"


def main() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE orders (id INT, customer_id INT, amount DECIMAL, status VARCHAR, created_at DATE);
        INSERT INTO orders VALUES
          (1, 1, 100, 'paid',     '2026-05-01'),
          (2, 1, 50,  'refunded', '2026-05-15'),
          (3, 2, 200, 'paid',     '2026-06-01');
    """)
    db = DuckDBConnector(conn)
    policy = Policy(
        invariants=["amount >= 0"],
        required_filters={"orders": ["created_at"]},
    )

    agent_outputs = [
        ("Total paid revenue in May 2026",
         "SELECT SUM(amount) AS revenue FROM orders "
         "WHERE status='paid' AND created_at >= '2026-05-01' AND created_at < '2026-06-01'"),
        ("Total revenue",                       # missing required date filter
         "SELECT SUM(amount) AS revenue FROM orders WHERE status='paid'"),
        ("All orders joined to customers",      # cartesian + missing table
         "SELECT * FROM orders, customers"),
    ]

    for question, sql in agent_outputs:
        decision = gate(sql, question, db, policy)
        print(f"[{decision.upper():7}] {question}")


if __name__ == "__main__":
    main()
