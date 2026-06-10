from verisql import verify


def test_schema_missing_table_flagged(duckdb_with_schema):
    r = verify(
        "SELECT * FROM nonexistent_table",
        dialect="duckdb",
        connector=duckdb_with_schema,
    )
    assert any(f.check == "schema_existence" and f.severity.value == "critical" for f in r.flags)


def test_schema_missing_column_flagged(duckdb_with_schema):
    r = verify(
        "SELECT c.nonexistent_col FROM customers c",
        dialect="duckdb",
        connector=duckdb_with_schema,
    )
    assert any(f.check == "schema_existence" and f.severity.value == "error" for f in r.flags)


def test_zero_row_flagged(duckdb_with_schema):
    r = verify(
        "SELECT * FROM customers WHERE name = 'Nobody'",
        dialect="duckdb",
        connector=duckdb_with_schema,
    )
    assert r.executed
    assert r.row_count == 0
    assert any(f.check == "zero_row_execution" for f in r.flags)


def test_nonzero_row_passes(duckdb_with_schema):
    r = verify(
        "SELECT * FROM customers WHERE name = 'Alice'",
        dialect="duckdb",
        connector=duckdb_with_schema,
    )
    assert r.executed
    assert r.row_count == 1
    assert not any(f.check == "zero_row_execution" for f in r.flags)


def test_mutation_refused(duckdb_with_schema):
    r = verify(
        "DELETE FROM customers",
        dialect="duckdb",
        connector=duckdb_with_schema,
    )
    # ast_parse will pass, but zero_row will raise PermissionError → CRITICAL flag
    assert any(f.check == "zero_row_execution" and f.severity.value == "critical" for f in r.flags)
