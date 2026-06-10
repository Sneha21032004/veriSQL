import re
from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity

DATE_HINTS = re.compile(
    r"\b(today|yesterday|last\s+\w+|this\s+(week|month|quarter|year)|"
    r"in\s+\d{4}|since\s+\w+|past\s+\w+|q[1-4]\b|recent|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)


class DateCoverageCheck(Check):
    """If user question mentions a time range, SQL should filter on a date column."""

    name = "date_coverage"

    def run(self, ctx: CheckContext, report: Report) -> None:
        if not ctx.question:
            return
        if not DATE_HINTS.search(ctx.question):
            return

        ast = ctx.ast()
        if ast is None:
            return

        # any column with date-ish name appearing in WHERE / HAVING?
        date_col_pattern = re.compile(r"(date|time|_at|_on|created|updated|timestamp)", re.IGNORECASE)
        found = False
        for select in ast.find_all(exp.Select):
            where = select.args.get("where")
            having = select.args.get("having")
            for clause in (where, having):
                if clause is None:
                    continue
                for col in clause.find_all(exp.Column):
                    if date_col_pattern.search(col.name):
                        found = True
                        break

        if not found:
            report.add(Flag(
                check=self.name,
                severity=Severity.ERROR,
                message=(
                    "Question specifies a time range but SQL has no date/time filter. "
                    "Likely returns wrong totals across all time."
                ),
                details={"question": ctx.question},
            ))
