from sqlglot import expressions as exp
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity


class SchemaCheck(Check):
    """Verify referenced tables and columns exist in the connected database."""

    name = "schema_existence"
    requires_connector = True

    def run(self, ctx: CheckContext, report: Report) -> None:
        ast = ctx.ast()
        if ast is None or ctx.connector is None:
            return

        # collect table refs
        tables: dict[str, str] = {}  # alias_or_name -> real_name
        for t in ast.find_all(exp.Table):
            real = t.name
            alias = t.alias_or_name
            tables[alias] = real

        known_tables = ctx.connector.list_tables()
        missing_tables = []
        for alias, real in tables.items():
            if real.lower() not in {n.lower() for n in known_tables}:
                missing_tables.append(real)

        if missing_tables:
            report.add(Flag(
                check=self.name,
                severity=Severity.CRITICAL,
                message=f"Tables not in schema: {missing_tables}",
                details={"missing_tables": missing_tables, "known": known_tables[:20]},
            ))
            return

        # column check: best-effort, qualified columns only
        bad_cols: list[str] = []
        for c in ast.find_all(exp.Column):
            col_name = c.name
            tbl_alias = c.table  # may be empty if unqualified
            if not tbl_alias:
                continue
            real_table = tables.get(tbl_alias, tbl_alias)
            try:
                cols = ctx.connector.list_columns(real_table)
            except Exception:
                continue
            if col_name.lower() not in {x.lower() for x in cols}:
                bad_cols.append(f"{tbl_alias}.{col_name}")

        if bad_cols:
            report.add(Flag(
                check=self.name,
                severity=Severity.ERROR,
                message=f"Columns not found: {bad_cols}",
                details={"missing_columns": bad_cols},
            ))
