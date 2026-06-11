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
                            if inner.expressions:
                                # literal list: only dangerous if it actually contains NULL
                                if any(isinstance(e, exp.Null) for e in inner.expressions):
                                    not_in_offenders.append(
                                        f"{col.sql()} NOT IN (...) — list contains NULL → ALWAYS empty result"
                                    )
                            elif inner.args.get("query") is not None:
                                # subquery: dangerous unless it guards its projection with IS NOT NULL
                                if not self._subquery_null_safe(inner.args["query"]):
                                    not_in_offenders.append(
                                        f"{col.sql()} NOT IN (subquery) — empty result if subquery yields NULL"
                                    )

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
    def _subquery_null_safe(query: exp.Expression) -> bool:
        """True if the NOT IN subquery filters NULLs out of its projected column."""
        sel = query.this if isinstance(query, exp.Subquery) else query
        if not isinstance(sel, exp.Select) or len(sel.expressions) != 1:
            return False
        proj = sel.expressions[0]
        col = proj.this if isinstance(proj, exp.Alias) else proj
        if not isinstance(col, exp.Column):
            return False
        where = sel.args.get("where")
        if where is None:
            return False
        target = col.sql()
        for not_node in where.find_all(exp.Not):
            inner = not_node.this
            if isinstance(inner, exp.Is) and isinstance(inner.expression, exp.Null):
                if inner.this.sql() == target:
                    return True
        return False

    @staticmethod
    def _has_null_guard(where: exp.Expression, col: exp.Column) -> bool:
        target = col.sql()
        for is_node in where.find_all(exp.Is):
            if isinstance(is_node.expression, exp.Null) and is_node.this.sql() == target:
                return True
        return False
