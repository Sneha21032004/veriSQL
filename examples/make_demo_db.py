"""Create demo_warehouse.duckdb — a tiny fintech warehouse with landmines.

The data is engineered so naive AI SQL gives WRONG answers that look right:
  - blocklist contains a NULL  -> NOT IN queries return zero rows
  - orders span months         -> missing date filter inflates revenue
  - timestamps have times      -> equality-with-date matches almost nothing
"""
import duckdb

conn = duckdb.connect("demo_warehouse.duckdb")
conn.execute("""
    DROP TABLE IF EXISTS customers; DROP TABLE IF EXISTS orders; DROP TABLE IF EXISTS blocklist;
    CREATE TABLE customers (id INT, name VARCHAR, email VARCHAR, region VARCHAR);
    CREATE TABLE orders (id INT, customer_id INT, amount DECIMAL(10,2),
                         status VARCHAR, created_at TIMESTAMP);
    CREATE TABLE blocklist (banned_region VARCHAR);

    INSERT INTO customers VALUES
      (1,'Asha','asha@x.in','IN'), (2,'Bob',NULL,'US'),
      (3,'Carol','c@x.uk','UK'),   (4,'Dan','d@x.ca','CA');

    INSERT INTO orders VALUES
      (1,1,1200.00,'paid','2026-05-03 14:22:01'),
      (2,2,800.00,'paid','2026-05-15 09:10:45'),
      (3,3,300.00,'refunded','2026-05-20 18:05:00'),
      (4,1,950.00,'paid','2026-06-02 11:00:30'),
      (5,4,400.00,'paid','2026-04-28 08:45:12');

    -- the landmine: one NULL row
    INSERT INTO blocklist VALUES ('US'), (NULL);
""")
conn.close()
print("demo_warehouse.duckdb created.")
print("Landmines armed: NULL in blocklist, multi-month orders, real timestamps.")
