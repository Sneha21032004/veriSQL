"""Labeled wrong-SQL corpus for measuring verisql catch-rate.

Each case is (question, sql, label, bug). label is "wrong" or "correct".
'wrong' cases carry a bug tag describing the silent failure mode. 'correct' cases
are realistic right answers used to measure the false-positive rate.

This is a seed corpus. Grow it from Spider/BIRD plus real misfires; the dataset is
the moat — catch-rate is only credible against labeled ground truth.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    question: str
    sql: str
    label: str   # "wrong" | "correct"
    bug: str     # short tag, "" for correct cases


SCHEMA_SQL = """
CREATE TABLE customers (
    id INTEGER PRIMARY KEY, name VARCHAR, email VARCHAR,
    country VARCHAR, created_at TIMESTAMP
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY, customer_id INTEGER, amount DECIMAL(10,2),
    status VARCHAR, created_at TIMESTAMP
);
CREATE TABLE refunds (
    id INTEGER PRIMARY KEY, order_id INTEGER, amount DECIMAL(10,2), created_at TIMESTAMP
);
INSERT INTO customers VALUES
  (1,'Alice','a@x.com','US','2026-01-15'),
  (2,'Bob',NULL,'US','2026-02-01'),
  (3,'Carol','c@x.com','UK','2026-03-10'),
  (4,'Dan',NULL,'CA','2026-04-05');
INSERT INTO orders VALUES
  (1,1,100.00,'paid','2026-05-01'),
  (2,1,50.00,'refunded','2026-05-15'),
  (3,2,200.00,'paid','2026-06-01'),
  (4,3,75.00,'paid','2026-05-20');
INSERT INTO refunds VALUES
  (1,2,50.00,'2026-05-16');
"""


CASES: list[Case] = [
    # ---- WRONG: silent failure modes -------------------------------------
    Case("Total revenue last month",
         "SELECT SUM(amount) FROM orders WHERE status='paid'",
         "wrong", "missing_date_filter"),
    Case("Customers with no email, excluding US",
         "SELECT * FROM customers WHERE country != 'US'",
         "wrong", "null_excluded_by_neq"),
    Case("Customers not in the VIP list",
         "SELECT * FROM customers WHERE id NOT IN (1, NULL)",
         "wrong", "not_in_null"),
    Case("All orders with their customer",
         "SELECT * FROM orders, customers",
         "wrong", "cartesian"),
    Case("Show every order",
         "SELECT * FROM orders",
         "wrong", "no_filter_large_table"),
    Case("Revenue by customer",
         "SELECT customer_id, SUM(amount) FROM orders, refunds GROUP BY customer_id",
         "wrong", "cartesian_aggregate_inflation"),
    Case("Orders in May 2026",
         "SELECT * FROM orders WHERE created_at = '2026-05-01'",
         "wrong", "equality_instead_of_range"),
    Case("Average order value this quarter",
         "SELECT AVG(amount) FROM orders",
         "wrong", "missing_date_filter"),
    Case("Paid orders from UK customers",
         "SELECT o.* FROM orders o, customers c WHERE o.status='paid'",
         "wrong", "cartesian_with_partial_filter"),
    Case("Customer lifetime value",
         "SELECT c.name, SUM(o.amount) FROM customers c, orders o GROUP BY c.name",
         "wrong", "cartesian"),
    Case("Refund rate",
         "SELECT COUNT(*) FROM refunds WHERE order_id != 2",
         "wrong", "null_excluded_by_neq"),
    Case("Total of completed orders since April",
         "SELECT SUM(amount) FROM orders WHERE status = 'complete'",
         "wrong", "missing_date_filter"),

    # ---- CORRECT: realistic right answers (false-positive control) --------
    Case("Total paid revenue in May 2026",
         "SELECT SUM(amount) FROM orders WHERE status='paid' "
         "AND created_at >= '2026-05-01' AND created_at < '2026-06-01'",
         "correct", ""),
    Case("Customers from the UK",
         "SELECT * FROM customers WHERE country = 'UK'",
         "correct", ""),
    Case("Each customer's paid order total in May",
         "SELECT c.name, SUM(o.amount) FROM customers c JOIN orders o ON c.id = o.customer_id "
         "WHERE o.status='paid' AND o.created_at >= '2026-05-01' AND o.created_at < '2026-06-01' "
         "GROUP BY c.name",
         "correct", ""),
    Case("Number of customers",
         "SELECT COUNT(*) FROM customers",
         "correct", ""),
    Case("Orders placed on 2026-05-01",
         "SELECT * FROM orders WHERE created_at >= '2026-05-01' AND created_at < '2026-05-02'",
         "correct", ""),
    Case("Refunded amount per order",
         "SELECT order_id, SUM(amount) FROM refunds GROUP BY order_id",
         "correct", ""),
    Case("Customers and their order count",
         "SELECT c.name, COUNT(o.id) FROM customers c "
         "LEFT JOIN orders o ON c.id = o.customer_id GROUP BY c.name",
         "correct", ""),
    Case("Top 10 orders by amount",
         "SELECT * FROM orders ORDER BY amount DESC LIMIT 10",
         "correct", ""),
]
