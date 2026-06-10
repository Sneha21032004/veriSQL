import sqlglot
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity


class AstParseCheck(Check):
    name = "ast_parse"
    requires_ast = False  # this check IS the AST parse

    def run(self, ctx: CheckContext, report: Report) -> None:
        try:
            ctx.parsed = sqlglot.parse_one(
                ctx.sql, read=ctx.dialect, error_level=sqlglot.ErrorLevel.IMMEDIATE
            )
        except sqlglot.errors.ParseError as e:
            report.add(Flag(
                check=self.name,
                severity=Severity.CRITICAL,
                message=f"SQL failed to parse: {e}",
                details={"error": str(e)},
            ))
            ctx.parsed = None
            return
        except Exception as e:
            report.add(Flag(
                check=self.name,
                severity=Severity.CRITICAL,
                message=f"Unexpected parse failure: {e}",
                details={"error": str(e)},
            ))
            ctx.parsed = None
