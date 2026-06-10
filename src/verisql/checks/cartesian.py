from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity


class CartesianCheck(Check):
    """Detect implicit cross joins / cartesian products.

    sqlglot normalizes `FROM a, b` into a Join node with empty `kind` and no `on`.
    Explicit CROSS JOIN gets `kind='CROSS'`.
    """

    name = "cartesian_join"

    def run(self, ctx: CheckContext, report: Report) -> None:
        ast = ctx.ast()
        if ast is None:
            return

        for select in ast.find_all(exp.Select):
            joins = select.args.get("joins") or []
            if not joins:
                continue

            unjoined: list[str] = []
            explicit_cross: list[str] = []

            for j in joins:
                kind = (j.kind or "").upper()
                side = (j.side or "").upper()
                on = j.args.get("on")
                using = j.args.get("using")
                tbl = j.this
                if isinstance(tbl, exp.Table):
                    tbl_alias = tbl.alias_or_name
                    tbl_name = tbl.name
                else:
                    tbl_alias = tbl_name = "<derived>"

                if kind == "CROSS":
                    explicit_cross.append(tbl_name)
                    continue

                # Implicit join (comma) or any join without ON/USING
                if not on and not using and not kind and not side:
                    # Check WHERE for a predicate tying this table (by alias) to another
                    if not self._where_has_join_predicate(select, tbl_alias):
                        unjoined.append(tbl_name)

            if explicit_cross:
                report.add(Flag(
                    check=self.name,
                    severity=Severity.WARN,
                    message=f"Explicit CROSS JOIN on {explicit_cross}. Confirm intentional.",
                    details={"tables": explicit_cross},
                ))

            if unjoined:
                report.add(Flag(
                    check=self.name,
                    severity=Severity.CRITICAL,
                    message=(
                        f"Possible cartesian product: tables {unjoined} have no JOIN predicate "
                        "and no equality with another table in WHERE."
                    ),
                    details={"tables": unjoined},
                ))

    @staticmethod
    def _where_has_join_predicate(select: exp.Select, table_alias: str) -> bool:
        where = select.args.get("where")
        if where is None:
            return False
        for eq in where.find_all(exp.EQ):
            l, r = eq.this, eq.expression
            if isinstance(l, exp.Column) and isinstance(r, exp.Column):
                if l.table and r.table and l.table != r.table:
                    if table_alias in (l.table, r.table):
                        return True
        return False
