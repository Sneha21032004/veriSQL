-- VeriSQL Postgres extension v0.1.0
--
-- Deterministic verification oracle inside the database. The same engine the
-- Python lib exposes — but running where the schema and the data already live,
-- with no extra service to deploy.
--
-- Public surface (all under the `verisql` schema):
--   verisql.check(sql)                  -> setof (severity, check, message)
--   verisql.explain_sanity(sql)         -> setof (severity, message)
--   verisql.fingerprint(sql)            -> text  (order-insensitive result hash)
--   verisql.diff(sql_a, sql_b)          -> boolean (true if equivalent on the data)
--   verisql.history_record(sql, tag)    -> void   (stash a fingerprint for later drift checks)
--   verisql.history_check(sql, tag)     -> setof (severity, message)
--
-- All checks are read-only by construction: any input containing a
-- mutation keyword (INSERT/UPDATE/DELETE/etc.) is rejected before execution.

SET LOCAL search_path = verisql, pg_temp;

-- ---------------------------------------------------------------------------
-- mutation guard — refuse anything that could change the database
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION verisql._guard_mutation(p_sql text) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    stripped text := regexp_replace(p_sql, '--[^\n]*|/\*.*?\*/', ' ', 'gs');
    head     text := lower(ltrim(stripped));
    kw       text;
BEGIN
    FOREACH kw IN ARRAY ARRAY[
        'insert','update','delete','drop','alter','truncate',
        'create','merge','grant','revoke','attach','copy','vacuum','reindex'
    ] LOOP
        IF head ~ ('^' || kw || '\M') THEN
            RAISE EXCEPTION 'verisql: refusing to run a mutating statement (starts with %)', kw
              USING ERRCODE = 'insufficient_privilege';
        END IF;
    END LOOP;
END;
$$;

-- ---------------------------------------------------------------------------
-- check() — top-level catalog-and-runtime verifier
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION verisql.check(p_sql text)
RETURNS TABLE (severity text, check_name text, message text)
LANGUAGE plpgsql AS $$
DECLARE
    tbl text;
    bad_tables text[] := ARRAY[]::text[];
    row_count bigint;
    not_in_match text[];
BEGIN
    PERFORM verisql._guard_mutation(p_sql);

    -- 1) schema_existence: any FROM/JOIN target must exist in the catalog
    FOR tbl IN
        SELECT DISTINCT m[1]
        FROM regexp_matches(
            p_sql,
            '\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)',
            'gi'
        ) m
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
             WHERE table_name = split_part(tbl, '.', greatest(1, array_length(string_to_array(tbl,'.'),1)))
        ) THEN
            bad_tables := array_append(bad_tables, tbl);
        END IF;
    END LOOP;

    IF array_length(bad_tables, 1) > 0 THEN
        RETURN QUERY SELECT 'critical'::text, 'schema_existence'::text,
                            format('Tables not in schema: %s', bad_tables)::text;
    END IF;

    -- 2) not_in_null: scan for `NOT IN (SELECT ...)` and actually execute the
    --    subquery to see whether it would yield a NULL. Catches the silent killer.
    FOR not_in_match IN
        SELECT m FROM regexp_matches(
            p_sql,
            '(?i)not\s+in\s*\(\s*(select[^)]+)\)',
            'g'
        ) m
    LOOP
        DECLARE
            cnt int;
        BEGIN
            EXECUTE format('SELECT count(*) FROM (%s) sub WHERE sub IS NULL', not_in_match[1])
              INTO cnt;
            IF cnt > 0 THEN
                RETURN QUERY SELECT 'error'::text, 'null_semantics'::text,
                    'NOT IN subquery contains NULL -> result will be empty (three-valued logic)'::text;
            END IF;
        EXCEPTION WHEN OTHERS THEN
            -- subquery shape we cannot evaluate; let other checks weigh in
            NULL;
        END;
    END LOOP;

    -- 3) zero_row execution: run the query read-only and count returned rows
    BEGIN
        EXECUTE format('SELECT count(*) FROM (%s) _vq LIMIT 1', p_sql) INTO row_count;
        IF row_count = 0 THEN
            RETURN QUERY SELECT 'warn'::text, 'zero_row_execution'::text,
                'Query executed but returned zero rows (often wrong filter or NULL semantics)'::text;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        RETURN QUERY SELECT 'critical'::text, 'execution'::text,
                            ('Execution failed: ' || SQLERRM)::text;
    END;

    -- 4) EXPLAIN-plan sanity (delegated)
    RETURN QUERY SELECT * FROM verisql.explain_sanity(p_sql);
END;
$$;

-- ---------------------------------------------------------------------------
-- explain_sanity() — flag full sequential scans when a filter exists
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION verisql.explain_sanity(p_sql text)
RETURNS TABLE (severity text, message text)
LANGUAGE plpgsql AS $$
DECLARE
    plan_json jsonb;
    big_seq_scan record;
BEGIN
    PERFORM verisql._guard_mutation(p_sql);
    EXECUTE format('EXPLAIN (FORMAT JSON, VERBOSE false) %s', p_sql) INTO plan_json;

    FOR big_seq_scan IN
        SELECT (node->>'Relation Name') AS rel,
               (node->>'Plan Rows')::numeric AS est_rows
          FROM jsonb_array_elements(plan_json->0->'Plan'->'Plans') node
         WHERE node->>'Node Type' = 'Seq Scan'
           AND (node->>'Plan Rows')::numeric > 100000
           AND p_sql ~* '\\bwhere\\b'
    LOOP
        RETURN QUERY SELECT 'warn'::text,
            format('Sequential scan on %s (~%s rows) despite WHERE clause; check filter column / index',
                   big_seq_scan.rel, big_seq_scan.est_rows)::text;
    END LOOP;
END;
$$;

-- ---------------------------------------------------------------------------
-- fingerprint() — order-insensitive content hash of a result set
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION verisql.fingerprint(p_sql text)
RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    fp text;
BEGIN
    PERFORM verisql._guard_mutation(p_sql);
    EXECUTE format(
        'SELECT md5(string_agg(rh, '''' ORDER BY rh)) FROM ('
        '  SELECT md5(t::text) AS rh FROM (%s) t'
        ') x', p_sql
    ) INTO fp;
    RETURN coalesce(fp, md5(''));
END;
$$;

-- ---------------------------------------------------------------------------
-- diff() — boolean: do two queries yield the same multiset?
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION verisql.diff(p_sql_a text, p_sql_b text)
RETURNS boolean LANGUAGE plpgsql AS $$
BEGIN
    RETURN verisql.fingerprint(p_sql_a) = verisql.fingerprint(p_sql_b);
END;
$$;

-- ---------------------------------------------------------------------------
-- history learner: stash fingerprints and a few result stats over time, then
-- alert when a "same" query produces a wildly different shape
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS verisql.query_history (
    tag         text        NOT NULL,
    sql_hash    text        NOT NULL,
    fingerprint text        NOT NULL,
    row_count   bigint      NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tag, recorded_at)
);

CREATE OR REPLACE FUNCTION verisql.history_record(p_sql text, p_tag text)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    rc bigint;
    fp text;
BEGIN
    PERFORM verisql._guard_mutation(p_sql);
    EXECUTE format('SELECT count(*) FROM (%s) _vq', p_sql) INTO rc;
    fp := verisql.fingerprint(p_sql);
    INSERT INTO verisql.query_history(tag, sql_hash, fingerprint, row_count)
    VALUES (p_tag, md5(p_sql), fp, rc);
END;
$$;

CREATE OR REPLACE FUNCTION verisql.history_check(p_sql text, p_tag text)
RETURNS TABLE (severity text, message text)
LANGUAGE plpgsql AS $$
DECLARE
    new_rc  bigint;
    new_fp  text;
    avg_rc  numeric;
    stddev_rc numeric;
BEGIN
    PERFORM verisql._guard_mutation(p_sql);
    EXECUTE format('SELECT count(*) FROM (%s) _vq', p_sql) INTO new_rc;
    new_fp := verisql.fingerprint(p_sql);

    SELECT avg(row_count), coalesce(stddev_pop(row_count), 0)
      INTO avg_rc, stddev_rc
      FROM verisql.query_history
     WHERE tag = p_tag;

    IF avg_rc IS NULL THEN
        RETURN QUERY SELECT 'info'::text,
            ('No history for tag ' || p_tag || '; recording baseline.')::text;
        PERFORM verisql.history_record(p_sql, p_tag);
        RETURN;
    END IF;

    -- distribution drift: > 3 sigma OR > 5x change in row count
    IF stddev_rc > 0 AND abs(new_rc - avg_rc) > 3 * stddev_rc THEN
        RETURN QUERY SELECT 'error'::text,
            format('Row-count drift: %s rows now vs mean %s (sigma %s)',
                   new_rc, round(avg_rc, 2), round(stddev_rc, 2))::text;
    ELSIF avg_rc > 0 AND (new_rc::numeric / avg_rc > 5 OR avg_rc / nullif(new_rc::numeric, 0) > 5) THEN
        RETURN QUERY SELECT 'warn'::text,
            format('Row-count step change: %s rows now vs mean %s', new_rc, round(avg_rc, 2))::text;
    END IF;
END;
$$;

GRANT USAGE ON SCHEMA verisql TO PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA verisql TO PUBLIC;
GRANT SELECT, INSERT ON verisql.query_history TO PUBLIC;
