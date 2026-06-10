from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity


class NullSemanticsCheck(Check):
    """Flag predicates that silently exclude NULL rows.

    `WHERE col != 'x'` excludes NULL rows even when the user likely wanted them.
    `WHERE col NOT IN (...)` does the same and is worse: if any value in the list
    is NULL the whole predicate is NULL → zero rows.
    """

    name = "null_semantics"

    def run(self, ctx: CheckContext, report: Report) -> None:
        ast = ctx.ast()
        if ast is None:
            return

        for select in ast.find_all(exp.Select):
            where = select.args.get("where")
            if where is None:
                continue

            neq_offenders: list[str] = []   # WARN: != drops NULL rows (often intended)
            not_in_offenders: list[str] = []  # ERROR: NOT IN with any NULL => empty result

            for node in where.find_all((exp.NEQ, exp.Not)):
                if isinstance(node, exp.NEQ):
                    lhs = node.this
                    if isinstance(lhs, exp.Column) and not self._has_null_guard(where, lhs):
                        neq_offenders.append(f"{lhs.sql()} != ... (excludes NULL rows)")
                elif isinstance(node, exp.Not):
                    inner = node.this
                    if isinstance(inner, exp.In):
                        col = inner.this
                        if isinstance(col, exp.Column) and not self._has_null_guard(where, col):
                            literal_null = any(
                                isinstance(e, exp.Null) for e in inner.expressions
                            )
                            tag = " — list contains NULL → ALWAYS empty result" if literal_null else ""
                            not_in_offenders.append(f"{col.sql()} NOT IN (...){tag}")

            if not_in_offenders:
                report.add(Flag(
                    check=self.name,
                    severity=Severity.ERROR,
                    message=(
                        "NOT IN excludes NULLs and returns no rows if the list/subquery yields "
                        "a NULL: " + "; ".join(not_in_offenders)
                    ),
                    details={"not_in": not_in_offenders},
                ))
            if neq_offenders:
                report.add(Flag(
                    check=self.name,
                    severity=Severity.WARN,
                    message="Predicates silently drop NULL rows: " + "; ".join(neq_offenders),
                    details={"neq": neq_offenders},
                ))

    @staticmethod
    def _has_null_guard(where: exp.Expression, col: exp.Column) -> bool:
        target = col.sql()
        for is_node in where.find_all(exp.Is):
            if isinstance(is_node.expression, exp.Null) and is_node.this.sql() == target:
                return True
        return False
