from verisql.verify import verify
from verisql.report import Report, Flag, Severity
from verisql.policy import Policy
from verisql.audit import AuditLog, AuditRecord
from verisql.equivalence import verify_equivalence, EquivalenceReport
from verisql.repair import verify_and_repair, repair_sql, RepairResult, Repair
from verisql.critic import (
    Critic,
    CriticRequest,
    CriticVerdict,
    anthropic_critic,
    openai_compatible_critic,
    should_escalate,
)

__all__ = [
    "verify",
    "Report",
    "Flag",
    "Severity",
    "Policy",
    "Critic",
    "CriticRequest",
    "CriticVerdict",
    "anthropic_critic",
    "openai_compatible_critic",
    "should_escalate",
    "AuditLog",
    "AuditRecord",
    "verify_equivalence",
    "EquivalenceReport",
    "verify_and_repair",
    "repair_sql",
    "RepairResult",
    "Repair",
]
__version__ = "0.1.0"
