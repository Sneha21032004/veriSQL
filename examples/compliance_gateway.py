"""End-to-end: AI-SQL compliance gateway with tamper-evident audit trail.

Scenario: a fintech data team lets analysts ask questions in English; an AI
writes SQL. Every query passes through verisql before a human sees the number,
and every decision lands in a hash-chained audit log — the evidence pack a
compliance officer hands to an auditor.
"""
import duckdb

from verisql import verify, Policy, AuditLog
from verisql.connectors.duckdb_conn import DuckDBConnector

POLICY = Policy(
    invariants=["amount >= 0"],
    required_filters={"transactions": ["txn_date"]},
    pii_columns={"customers": ["email", "phone", "pan_number"]},
)


def main() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE customers (id INT, name VARCHAR, email VARCHAR, phone VARCHAR,
                                pan_number VARCHAR, segment VARCHAR);
        CREATE TABLE transactions (id INT, customer_id INT, amount DECIMAL,
                                   txn_type VARCHAR, txn_date DATE);
        INSERT INTO customers VALUES
          (1,'Asha','asha@x.in','98xxxxxx01','ABCPX1234A','retail'),
          (2,'Vikram',NULL,'98xxxxxx02','XYZPV5678B','hni');
        INSERT INTO transactions VALUES
          (1,1,5000,'upi','2026-06-01'),
          (2,2,250000,'neft','2026-06-02');
    """)
    db = DuckDBConnector(conn)
    log = AuditLog("audit_trail.jsonl")

    ai_queries = [
        ("Total UPI volume this month",
         "SELECT SUM(amount) FROM transactions WHERE txn_type='upi' "
         "AND txn_date >= '2026-06-01'"),
        ("List HNI customers with contact details",          # PII exposure
         "SELECT * FROM customers WHERE segment = 'hni'"),
        ("All transactions",                                  # missing mandated date filter
         "SELECT * FROM transactions"),
    ]

    for question, sql in ai_queries:
        report = verify(sql, question=question, dialect="duckdb",
                        connector=db, policy=POLICY)
        rec = log.record(report, actor="analyst@nbfc.in", generator="text2sql-bot")
        print(f"[{rec.decision.upper():9}] {question}")
        for f in report.flags:
            print(f"     - {f.severity.value}: {f.message[:90]}")

    print("\n--- evidence pack ---")
    import json
    print(json.dumps(log.evidence_pack(), indent=2))


if __name__ == "__main__":
    main()
