from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


class Flag(BaseModel):
    check: str
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class Report(BaseModel):
    question: str | None = None
    sql: str
    dialect: str
    flags: list[Flag] = Field(default_factory=list)
    confidence: float = 1.0
    suggested_review: bool = False
    executed: bool = False
    row_count: int | None = None
    critic_invoked: bool = False
    critic_tokens: int = 0

    def add(self, flag: Flag) -> None:
        self.flags.append(flag)
        # confidence penalty per severity
        penalty = {
            Severity.INFO: 0.02,
            Severity.WARN: 0.10,
            Severity.ERROR: 0.30,
            Severity.CRITICAL: 0.60,
        }[flag.severity]
        self.confidence = max(0.0, self.confidence - penalty)
        if flag.severity in (Severity.ERROR, Severity.CRITICAL):
            self.suggested_review = True
        if flag.severity == Severity.WARN and self.confidence < 0.7:
            self.suggested_review = True

    def has_blocking(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.flags)

    def summary(self) -> str:
        lines = [
            f"SQL Verify Report (confidence={self.confidence:.2f})",
            f"  dialect: {self.dialect}",
            f"  flags: {len(self.flags)}",
            f"  review: {'YES' if self.suggested_review else 'no'}",
        ]
        if self.critic_invoked:
            lines.append(f"  critic: invoked ({self.critic_tokens} tokens)")
        for f in self.flags:
            lines.append(f"  [{f.severity.value.upper()}] {f.check}: {f.message}")
        return "\n".join(lines)
