from verisql import verify, Policy

PII_POLICY = Policy(pii_columns={"customers": ["email", "phone", "pan_number"]})


def test_select_star_on_governed_table_errors():
    r = verify("SELECT * FROM customers", dialect="duckdb", policy=PII_POLICY)
    assert any(f.check == "pii_access" and f.severity.value == "error" for f in r.flags)


def test_explicit_pii_column_warns():
    r = verify("SELECT email FROM customers WHERE id = 1", dialect="duckdb", policy=PII_POLICY)
    assert any(f.check == "pii_access" and f.severity.value == "warn" for f in r.flags)


def test_non_pii_projection_passes():
    r = verify("SELECT id, country FROM customers", dialect="duckdb", policy=PII_POLICY)
    assert not any(f.check == "pii_access" for f in r.flags)


def test_ungoverned_table_ignored():
    r = verify("SELECT email FROM vendors", dialect="duckdb", policy=PII_POLICY)
    assert not any(f.check == "pii_access" for f in r.flags)


def test_policy_yaml_roundtrip():
    p = Policy.from_dict({"pii_columns": {"customers": ["email"]}})
    assert p.pii_columns == {"customers": ["email"]}
