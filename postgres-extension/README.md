# verisql — Postgres extension

Deterministic verification oracle for AI-generated SQL, **inside the database** —
no extra service, no client library required. Pure PL/pgSQL, runs on any
PostgreSQL 13+, distributed as a `CREATE EXTENSION` install.

This is the server-side companion to the Python lib. It covers the checks that
benefit from running where the catalog and the data already are (schema lookup,
NOT IN subquery NULL detection, query-plan inspection, read-only execution,
result-set fingerprinting, and historical drift detection). For AST analysis
(cartesian joins, complex NULL-semantics rewrites) use the Python lib.

## Install

```bash
cd postgres-extension
sudo make install                       # uses pg_config to find your install
psql -c "CREATE EXTENSION verisql;"
```

That's it. Functions live under the `verisql` schema.

## Use

```sql
-- catch a silent failure right in the database
SELECT *
  FROM verisql.check('
    SELECT name FROM customers
    WHERE region NOT IN (SELECT banned_region FROM blocklist)
  ');

--  severity |     check_name     |                              message
-- ----------+--------------------+-------------------------------------------------------------------
--  error    | null_semantics     | NOT IN subquery contains NULL -> result will be empty (...)
--  warn     | zero_row_execution | Query executed but returned zero rows (...)
```

```sql
-- prove two queries are equivalent on the current data
SELECT verisql.diff(
    'SELECT id FROM orders WHERE status = ''paid''',
    'SELECT id FROM orders WHERE status != ''refunded'' AND status != ''pending'''
);
--  diff
-- ------
--  true / false
```

```sql
-- track a dashboard query so future runs flag drift / step changes
SELECT verisql.history_record(
    'SELECT sum(amount) FROM orders WHERE created_at >= now() - interval ''7 days''',
    'weekly_revenue'
);

SELECT * FROM verisql.history_check(
    'SELECT sum(amount) FROM orders WHERE created_at >= now() - interval ''7 days''',
    'weekly_revenue'
);
```

## Safety

Every function calls a `_guard_mutation` precheck that rejects any statement
starting with a mutation keyword (INSERT/UPDATE/DELETE/DROP/etc., comments
stripped first). The extension is marked `trusted` so non-superusers can install
it; nothing it does requires escalated privileges.

## Why a Postgres extension

The Python lib runs at the agent / client. The extension runs at the database
— closer to the schema, the statistics, and the data — and is installable with
one command on the 8M+ Postgres instances already in production. Same engine,
two surfaces.
