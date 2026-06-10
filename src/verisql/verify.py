from typing import Any
from verisql.checks import DEFAULT_CHECKS, Check, CheckContext
from verisql.report import Flag, Report, Severity
from verisql.critic import (
    Critic,
    CriticRequest,
    DEFAULT_GATE_LO,
    DEFAULT_GATE_HI,
    should_escalate,
)


def verify(
    sql: str,
    question: str | None = None,
    dialect: str = "duckdb",
    connector: Any = None,
    policy: Any = None,
    checks: list[type[Check]] | None = None,
    critic: Critic | None = None,
    gate_lo: float = DEFAULT_GATE_LO,
    gate_hi: float = DEFAULT_GATE_HI,
) -> Report:
    """Verify an LLM-generated SQL statement.

    Pipeline: deterministic checks run first and are free. The optional LLM
    `critic` is gated — it fires only when the deterministic confidence is
    ambiguous (in [gate_lo, gate_hi]) and a question exists to judge intent
    against. This keeps token spend near zero for the common case.

    Args:
        sql: SQL string to verify.
        question: natural-language question that produced the SQL (enables intent checks).
        dialect: sqlglot dialect (postgres, snowflake, bigquery, duckdb, ...).
        connector: optional DB adapter — enables schema, EXPLAIN, execution, invariants.
        policy: optional Policy with business invariants and required filters.
        checks: override the deterministic check list (defaults to DEFAULT_CHECKS).
        critic: optional LLM critic callable for ambiguous cases.
        gate_lo, gate_hi: confidence band in which the critic is allowed to run.

    Returns:
        Report with confidence score, flags, and review recommendation.
    """
    ctx = CheckContext(
        sql=sql, dialect=dialect, question=question, connector=connector, policy=policy
    )
    report = Report(question=question, sql=sql, dialect=dialect)

    for cls in checks or DEFAULT_CHECKS:
        if not cls.applies(ctx):
            continue
        try:
            cls().run(ctx, report)
        except Exception as e:  # a buggy check must never crash the verifier
            report.add(Flag(
                check=cls.name or cls.__name__,
                severity=Severity.INFO,
                message=f"Check raised: {e}",
                details={"error": str(e)},
            ))
        # unparseable SQL halts the pipeline — downstream checks would only error
        if report.has_blocking() and cls.name == "ast_parse":
            return report

    _maybe_run_critic(ctx, report, critic, gate_lo, gate_hi)
    return report


def _maybe_run_critic(
    ctx: CheckContext,
    report: Report,
    critic: Critic | None,
    gate_lo: float,
    gate_hi: float,
) -> None:
    if critic is None:
        return
    if not should_escalate(
        confidence=report.confidence,
        has_question=bool(ctx.question),
        has_blocking=report.has_blocking(),
        gate_lo=gate_lo,
        gate_hi=gate_hi,
    ):
        return

    req = CriticRequest(
        question=ctx.question or "",
        sql=ctx.sql,
        dialect=ctx.dialect,
        deterministic_confidence=report.confidence,
        schema_hint=_schema_hint(ctx),
    )
    try:
        verdict = critic(req)
    except Exception as e:
        report.add(Flag(
            check="llm_critic",
            severity=Severity.INFO,
            message=f"Critic raised: {e}",
            details={"error": str(e)},
        ))
        return

    report.critic_invoked = True
    report.critic_tokens = verdict.tokens_used
    if not verdict.agrees:
        report.add(Flag(
            check="llm_critic",
            severity=Severity.ERROR,
            message=f"LLM critic disagrees ({verdict.confidence:.2f}): {verdict.reason}",
            details={"critic_confidence": verdict.confidence, "reason": verdict.reason},
        ))
    else:
        # critic confirms intent — modest confidence boost, capped at 1.0
        report.confidence = min(1.0, report.confidence + 0.15 * verdict.confidence)


def _schema_hint(ctx: CheckContext) -> str | None:
    """Compact table:col list for the critic prompt — keeps the LLM call cheap."""
    conn = ctx.connector
    if conn is None:
        return None
    ast = ctx.ast()
    if ast is None:
        return None
    from sqlglot import expressions as exp

    parts: list[str] = []
    seen: set[str] = set()
    for t in ast.find_all(exp.Table):
        name = t.name
        if name in seen:
            continue
        seen.add(name)
        try:
            cols = conn.list_columns(name)
        except Exception:
            continue
        if cols:
            parts.append(f"{name}({', '.join(cols[:12])})")
    return "; ".join(parts) if parts else None
