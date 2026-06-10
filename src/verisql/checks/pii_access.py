from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity


class PIIAccessCheck(Check):
    """Flag queries that select governed PII columns.

    Driven by policy.pii_columns: {table: [column, ...]}. Any SELECT that
    projects a governed column (directly or via SELECT *) is flagged so the
    access lands in the audit trail with severity. Aimed at DPDP / GDPR / RBI
    data-access governance: AI-generated queries must not silently widen access
    to personal data.
    """

    name = "pii_access"
    requires_ast = True

    @classmethod
    def applies(cls, ctx: CheckContext) -> bool:
        return bool(ctx.policy and getattr(ctx.policy, "pii_columns", None)) and ctx.ast() is not None

    def run(self, ctx: CheckContext, report: Report) -> None:
        ast = ctx.ast()
        if ast is None or ctx.policy is None:
            return
        rules = {t.lower(): {c.lower() for c in cols}
                 for t, cols in ctx.policy.pii_columns.items()}

        for select in ast.find_all(exp.Select):
            tables = {t.name.lower() for t in select.find_all(exp.Table)}
            governed_tables = tables & rules.keys()
            if not governed_tables:
                continue

            # SELECT * over a governed table = automatic exposure
            has_star = any(isinstance(p, exp.Star) for p in select.expressions)
            if has_star:
                report.add(Flag(
                    check=self.name,
                    severity=Severity.ERROR,
                    message=(
                        f"SELECT * over PII-governed table(s) {sorted(governed_tables)} "
                        "exposes all personal-data columns. Project explicit columns."
                    ),
                    details={"tables": sorted(governed_tables)},
                ))
                continue

            exposed: list[str] = []
            governed_cols = set().union(*(rules[t] for t in governed_tables))
            for col in select.find_all(exp.Column):
                if col.name.lower() in governed_cols:
                    exposed.append(col.name.lower())

            if exposed:
                report.add(Flag(
                    check=self.name,
                    severity=Severity.WARN,
                    message=(
                        f"Query accesses PII column(s) {sorted(set(exposed))}. "
                        "Access recorded for audit; confirm purpose limitation."
                    ),
                    details={"columns": sorted(set(exposed)), "tables": sorted(governed_tables)},
                ))
