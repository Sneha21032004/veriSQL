from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.policy import InvariantEvaluator
from verisql.report import Flag, Report, Severity

# how many result rows to sample when checking value invariants
_SAMPLE_ROWS = 200


class RequiredFilterCheck(Check):
    """Enforce policy.required_filters: named tables must be filtered on named columns."""

    name = "required_filter"
    requires_ast = True

    @classmethod
    def applies(cls, ctx: CheckContext) -> bool:
        return bool(ctx.policy and ctx.policy.required_filters) and ctx.ast() is not None

    def run(self, ctx: CheckContext, report: Report) -> None:
        ast = ctx.ast()
        if ast is None or ctx.policy is None:
            return

        rules = {k.lower(): {c.lower() for c in v} for k, v in ctx.policy.required_filters.items()}

        for select in ast.find_all(exp.Select):
            tables = {t.name.lower() for t in select.find_all(exp.Table)}
            governed = tables & rules.keys()
            if not governed:
                continue

            where = select.args.get("where")
            filtered_cols: set[str] = set()
            if where is not None:
                filtered_cols = {c.name.lower() for c in where.find_all(exp.Column)}

            for tbl in governed:
                missing = rules[tbl] - filtered_cols
                if missing:
                    report.add(Flag(
                        check=self.name,
                        severity=Severity.ERROR,
                        message=(
                            f"Policy requires table '{tbl}' to be filtered on {sorted(rules[tbl])}; "
                            f"missing filter on {sorted(missing)}."
                        ),
                        details={"table": tbl, "missing_filters": sorted(missing)},
                    ))


class InvariantCheck(Check):
    """Execute the query (read-only) and assert policy.invariants hold on the result."""

    name = "business_invariant"
    requires_connector = True

    @classmethod
    def applies(cls, ctx: CheckContext) -> bool:
        return (
            bool(ctx.policy and ctx.policy.invariants)
            and ctx.connector is not None
            and ctx.ast() is not None
        )

    def run(self, ctx: CheckContext, report: Report) -> None:
        if ctx.policy is None or ctx.connector is None:
            return

        # reuse cached result if zero_row check already executed; else run now
        rows = ctx.cache.get("result_rows")
        columns = ctx.cache.get("result_columns")
        if rows is None:
            try:
                rows, columns = self._execute(ctx)
            except Exception as e:
                report.add(Flag(
                    check=self.name,
                    severity=Severity.WARN,
                    message=f"Could not execute query to check invariants: {e}",
                    details={"error": str(e)},
                ))
                return
            ctx.cache["result_rows"] = rows
            ctx.cache["result_columns"] = columns

        if not rows or not columns:
            return

        evaluators = [(inv, InvariantEvaluator(inv)) for inv in ctx.policy.invariants]
        violations: dict[str, int] = {}

        for raw in rows[:_SAMPLE_ROWS]:
            row = dict(zip(columns, raw))
            for inv, ev in evaluators:
                result = ev.check(row)
                if result is False:
                    violations[inv] = violations.get(inv, 0) + 1

        for inv, count in violations.items():
            report.add(Flag(
                check=self.name,
                severity=Severity.CRITICAL,
                message=f"Invariant violated in {count} row(s): {inv}",
                details={"invariant": inv, "violating_rows": count},
            ))

    @staticmethod
    def _execute(ctx: CheckContext) -> tuple[list[tuple], list[str]]:
        conn = ctx.connector
        rows = conn.execute_readonly(ctx.sql, max_rows=_SAMPLE_ROWS)  # type: ignore[union-attr]
        # column names: derive from sqlglot select projections
        columns: list[str] = []
        ast = ctx.ast()
        if ast is not None:
            sel = ast.find(exp.Select)
            if sel is not None:
                for proj in sel.expressions:
                    columns.append(proj.alias_or_name or proj.sql())
        return rows, columns
