from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity

# tables that almost always require a filter — overridable via config later
DEFAULT_LARGE_TABLES = {"orders", "events", "transactions", "logs", "audit_log", "telemetry"}


class FilterRequiredCheck(Check):
    """SELECT against large/transactional tables without WHERE is almost always wrong."""

    name = "filter_required"

    def __init__(self, large_tables: set[str] | None = None):
        self.large_tables = {t.lower() for t in (large_tables or DEFAULT_LARGE_TABLES)}

    def run(self, ctx: CheckContext, report: Report) -> None:
        ast = ctx.ast()
        if ast is None:
            return

        for select in ast.find_all(exp.Select):
            tables = [t.name.lower() for t in select.find_all(exp.Table)]
            risky = [t for t in tables if t in self.large_tables]
            if not risky:
                continue
            has_where = select.args.get("where") is not None
            has_limit = select.args.get("limit") is not None
            if not has_where and not has_limit:
                report.add(Flag(
                    check=self.name,
                    severity=Severity.ERROR,
                    message=(
                        f"Query against large table(s) {risky} has no WHERE clause "
                        "and no LIMIT. Likely scans full table."
                    ),
                    details={"risky_tables": risky},
                ))
