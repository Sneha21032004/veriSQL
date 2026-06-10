from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
import sqlglot
from sqlglot import expressions as exp

if TYPE_CHECKING:
    from verisql.connectors.base import Connector
    from verisql.policy import Policy
    from verisql.report import Report


@dataclass
class CheckContext:
    sql: str
    dialect: str
    question: str | None = None
    parsed: exp.Expression | None = None
    connector: "Connector | None" = None
    policy: "Policy | None" = None
    cache: dict[str, Any] = field(default_factory=dict)

    def ast(self) -> exp.Expression | None:
        if self.parsed is not None:
            return self.parsed
        try:
            self.parsed = sqlglot.parse_one(self.sql, read=self.dialect)
        except Exception:
            self.parsed = None
        return self.parsed


class Check:
    """Subclass and implement run(). Append Flags to report."""

    name: str = ""
    requires_connector: bool = False
    requires_ast: bool = True

    def run(self, ctx: CheckContext, report: "Report") -> None:
        raise NotImplementedError

    @classmethod
    def applies(cls, ctx: CheckContext) -> bool:
        if cls.requires_connector and ctx.connector is None:
            return False
        if cls.requires_ast and ctx.ast() is None:
            return False
        return True
