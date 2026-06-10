from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity

# capped so a downstream invariant check can reuse this result set
_EXEC_ROWS = 200


class ZeroRowCheck(Check):
    """Execute SQL read-only; zero rows on an aggregate-less query is often wrong answer.

    Caches the result rows + column names in ctx.cache so later checks
    (e.g. business invariants) reuse them instead of re-executing the query.
    """

    name = "zero_row_execution"
    requires_connector = True

    def run(self, ctx: CheckContext, report: Report) -> None:
        if ctx.connector is None:
            return
        try:
            rows = ctx.connector.execute_readonly(ctx.sql, max_rows=_EXEC_ROWS)
        except Exception as e:
            report.add(Flag(
                check=self.name,
                severity=Severity.CRITICAL,
                message=f"Execution failed: {e}",
                details={"error": str(e)},
            ))
            return

        report.executed = True
        report.row_count = len(rows)
        ctx.cache["result_rows"] = rows
        ctx.cache["result_columns"] = self._column_names(ctx)

        if len(rows) == 0:
            report.add(Flag(
                check=self.name,
                severity=Severity.WARN,
                message=(
                    "Query executed but returned zero rows. Often indicates wrong filter, "
                    "stale data assumption, or NULL-semantic issue."
                ),
            ))

    @staticmethod
    def _column_names(ctx: CheckContext) -> list[str]:
        ast = ctx.ast()
        if ast is None:
            return []
        sel = ast.find(exp.Select)
        if sel is None:
            return []
        return [proj.alias_or_name or proj.sql() for proj in sel.expressions]
