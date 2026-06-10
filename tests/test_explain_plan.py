from verisql import verify
from verisql.checks.explain_plan import ExplainPlanCheck
from verisql.checks.base import CheckContext


def test_explain_runs_without_executing(duckdb_with_schema):
    # small table → no flag, but must not raise and must use the plan path
    r = verify(
        "SELECT * FROM orders WHERE status = 'paid'",
        dialect="duckdb",
        connector=duckdb_with_schema,
    )
    assert not any(f.check == "explain_plan" and f.severity.value == "error" for f in r.flags)


def test_max_estimated_rows_parser():
    plan = "SEQ_SCAN  orders  (rows=250000)\n  FILTER (rows=10)"
    assert ExplainPlanCheck._max_estimated_rows(plan) == 250000


def test_explain_skipped_without_capability():
    class NoExplain:
        dialect = "duckdb"
        def list_tables(self): return ["orders"]
        def list_columns(self, t): return ["id"]
        def execute_readonly(self, sql, max_rows=100): return []

    ctx = CheckContext(sql="SELECT * FROM orders", dialect="duckdb", connector=NoExplain())
    assert ExplainPlanCheck.applies(ctx) is False
