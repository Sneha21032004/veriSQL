import re
from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity

# column-name signals that the column is a timestamp/datetime (not a plain date)
_TS_NAME = re.compile(r"(_at$|_ts$|timestamp|datetime|created|updated|modified)", re.IGNORECASE)
# a literal that looks date-only (no time component)
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TimestampEqualityCheck(Check):
    """Flag `timestamp_col = 'YYYY-MM-DD'` — matches only the exact midnight instant.

    A very common silent failure: the user means "on that day" but equality against a
    timestamp column only matches rows at exactly 00:00:00. Almost always returns far
    fewer rows than intended. The fix is a half-open range
    [date, date+1). This check needs no database connection.
    """

    name = "timestamp_equality"

    def run(self, ctx: CheckContext, report: Report) -> None:
        ast = ctx.ast()
        if ast is None:
            return

        offenders: list[str] = []
        for eq in ast.find_all(exp.EQ):
            col, lit = eq.this, eq.expression
            # support either operand order
            if not isinstance(col, exp.Column):
                col, lit = lit, eq.this
            if not isinstance(col, exp.Column) or not isinstance(lit, exp.Literal):
                continue
            if not _TS_NAME.search(col.name):
                continue
            value = str(lit.this)
            if _DATE_ONLY.match(value):
                offenders.append(f"{col.sql()} = '{value}'")

        if offenders:
            report.add(Flag(
                check=self.name,
                severity=Severity.ERROR,
                message=(
                    "Equality on a timestamp column with a date-only literal matches only "
                    "exact midnight: " + "; ".join(offenders) +
                    ". Use a half-open range [d, d+1)."
                ),
                details={"offenders": offenders},
            ))
