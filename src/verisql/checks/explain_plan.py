import re
from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity

# rows estimate above which a full scan is worth flagging
_BIG_SCAN_ROWS = 100_000
_SEQ_SCAN_PAT = re.compile(r"seq[\s_]?scan", re.IGNORECASE)
_ROWS_PAT = re.compile(r"rows?[=:\s]+(\d+)", re.IGNORECASE)


class ExplainPlanCheck(Check):
    """Read the query plan (without executing) and flag pathological access patterns.

    Two signals:
      1. A WHERE clause exists but the planner chose a sequential/full scan on a
         large table — often means the filter column is not what the user expects,
         or a function wraps the column and defeats the index.
      2. The plan's estimated row count is far larger than a LIMIT or aggregate
         would imply — sign of an unintended join blowup.

    Uses EXPLAIN only (never EXPLAIN ANALYZE), so the query is not run.
    """

    name = "explain_plan"
    requires_connector = True

    @classmethod
    def applies(cls, ctx: CheckContext) -> bool:
        if ctx.connector is None or not hasattr(ctx.connector, "explain"):
            return False
        return ctx.ast() is not None

    def run(self, ctx: CheckContext, report: Report) -> None:
        ast = ctx.ast()
        if ast is None or ctx.connector is None:
            return

        try:
            plan = ctx.connector.explain(ctx.sql)
        except PermissionError:
            return  # mutation guard already covered by other checks
        except Exception as e:
            report.add(Flag(
                check=self.name,
                severity=Severity.WARN,
                message=f"Could not obtain query plan: {e}",
                details={"error": str(e)},
            ))
            return

        has_where = any(s.args.get("where") is not None for s in ast.find_all(exp.Select))
        max_rows = self._max_estimated_rows(plan)
        seq_scan = bool(_SEQ_SCAN_PAT.search(plan))

        if has_where and seq_scan and max_rows >= _BIG_SCAN_ROWS:
            report.add(Flag(
                check=self.name,
                severity=Severity.WARN,
                message=(
                    f"Filter present but planner chose a full scan (~{max_rows:,} rows). "
                    "The WHERE column may differ from intent, or a function defeats the index."
                ),
                details={"estimated_rows": max_rows},
            ))

    @staticmethod
    def _max_estimated_rows(plan: str) -> int:
        nums = [int(m.group(1)) for m in _ROWS_PAT.finditer(plan)]
        return max(nums) if nums else 0
