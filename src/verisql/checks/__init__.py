from verisql.checks.base import Check, CheckContext
from verisql.checks.ast_parse import AstParseCheck
from verisql.checks.schema import SchemaCheck
from verisql.checks.cartesian import CartesianCheck
from verisql.checks.null_semantics import NullSemanticsCheck
from verisql.checks.timestamp_equality import TimestampEqualityCheck
from verisql.checks.filter_required import FilterRequiredCheck
from verisql.checks.date_coverage import DateCoverageCheck
from verisql.checks.explain_plan import ExplainPlanCheck
from verisql.checks.zero_row import ZeroRowCheck
from verisql.checks.invariants import RequiredFilterCheck, InvariantCheck
from verisql.checks.pii_access import PIIAccessCheck

# Order is intentional:
#  - structural/free checks first (no DB, no execution)
#  - explain (DB metadata, no execution) next
#  - zero_row executes once and caches the result set
#  - invariant reuses the cached result set
DEFAULT_CHECKS: list[type[Check]] = [
    AstParseCheck,
    SchemaCheck,
    CartesianCheck,
    NullSemanticsCheck,
    TimestampEqualityCheck,
    PIIAccessCheck,
    RequiredFilterCheck,
    FilterRequiredCheck,
    DateCoverageCheck,
    ExplainPlanCheck,
    ZeroRowCheck,
    InvariantCheck,
]

__all__ = [
    "Check",
    "CheckContext",
    "DEFAULT_CHECKS",
    "AstParseCheck",
    "SchemaCheck",
    "CartesianCheck",
    "NullSemanticsCheck",
    "TimestampEqualityCheck",
    "PIIAccessCheck",
    "FilterRequiredCheck",
    "DateCoverageCheck",
    "ExplainPlanCheck",
    "ZeroRowCheck",
    "RequiredFilterCheck",
    "InvariantCheck",
]
