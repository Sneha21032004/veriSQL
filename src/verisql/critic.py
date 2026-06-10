"""Optional LLM critic — the escalation tier.

Design principle: deterministic checks are free. The LLM is the most expensive
resource in the pipeline, so it is gated. The critic fires only when the
deterministic verdict is *ambiguous* (confidence in a configurable band) and a
natural-language question is available to judge intent against. In practice this
means the overwhelming majority of queries never spend a single LLM token.

A critic is any callable:  (CriticRequest) -> CriticVerdict.
Wire your own model, or use the bundled Anthropic adapter (cheap model by default).
"""
from dataclasses import dataclass
from typing import Callable, Protocol


# ambiguity band: deterministic confidence inside [lo, hi] is "unsure" → escalate.
# Outside the band the deterministic layer is confident enough; do not spend tokens.
DEFAULT_GATE_LO = 0.40
DEFAULT_GATE_HI = 0.80


@dataclass
class CriticRequest:
    question: str
    sql: str
    dialect: str
    deterministic_confidence: float
    schema_hint: str | None = None  # compact table/column list, not full DDL


@dataclass
class CriticVerdict:
    agrees: bool          # does the SQL answer the question?
    confidence: float     # critic's own confidence 0..1
    reason: str
    tokens_used: int = 0


Critic = Callable[[CriticRequest], CriticVerdict]


class _SupportsMessages(Protocol):  # minimal structural type for the Anthropic client
    messages: object


_PROMPT = """You are a SQL correctness auditor. Decide if the SQL answers the QUESTION.
Be terse. Judge intent, joins, filters, date ranges, and aggregation grain.

QUESTION: {question}

SQL ({dialect}):
{sql}

{schema_block}Respond with exactly one line of JSON:
{{"agrees": true|false, "confidence": 0.0-1.0, "reason": "<=20 words"}}"""


def anthropic_critic(
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 200,
    client: object | None = None,
) -> Critic:
    """Build a critic backed by the Anthropic API. Cheap model by default.

    Lazy-imports `anthropic`; only call this if you intend to use it.
    """
    if client is None:
        import anthropic  # lazy
        client = anthropic.Anthropic()

    def _critic(req: CriticRequest) -> CriticVerdict:
        resp = client.messages.create(  # type: ignore[attr-defined]
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": _build_prompt(req)}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        usage = getattr(resp, "usage", None)
        tokens = (getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0)) if usage else 0
        return _parse_verdict(text, tokens)

    return _critic


def _build_prompt(req: CriticRequest) -> str:
    schema_block = f"SCHEMA: {req.schema_hint}\n\n" if req.schema_hint else ""
    return _PROMPT.format(
        question=req.question, dialect=req.dialect, sql=req.sql, schema_block=schema_block
    )


def _parse_verdict(text: str, tokens: int) -> CriticVerdict:
    """Parse the single-line JSON verdict any model returns. Provider-independent."""
    import json
    import re

    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return CriticVerdict(agrees=True, confidence=0.0, reason="unparseable critic output", tokens_used=tokens)
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return CriticVerdict(agrees=True, confidence=0.0, reason="invalid critic JSON", tokens_used=tokens)
    return CriticVerdict(
        agrees=bool(data.get("agrees", True)),
        confidence=float(data.get("confidence", 0.0)),
        reason=str(data.get("reason", ""))[:200],
        tokens_used=tokens,
    )


def openai_compatible_critic(
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
    max_tokens: int = 200,
    client: object | None = None,
) -> Critic:
    """Build a critic backed by any OpenAI-compatible Chat Completions endpoint.

    Works with OpenAI, Groq, DeepSeek, Together, Fireworks, OpenRouter, vLLM, and
    local Ollama (base_url='http://localhost:11434/v1'). The point: you do NOT need
    an Anthropic key — bring whatever model/provider you already pay for, or run a
    free local model.

    Examples:
        openai_compatible_critic("gpt-4o-mini")                       # OpenAI
        openai_compatible_critic("llama-3.1-8b-instant",
                                 base_url="https://api.groq.com/openai/v1")
        openai_compatible_critic("qwen2.5-coder:7b",
                                 base_url="http://localhost:11434/v1",
                                 api_key="ollama")                    # free, local
    """
    if client is None:
        from openai import OpenAI  # lazy
        client = OpenAI(base_url=base_url, api_key=api_key)

    def _critic(req: CriticRequest) -> CriticVerdict:
        resp = client.chat.completions.create(  # type: ignore[attr-defined]
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": _build_prompt(req)}],
        )
        text = (resp.choices[0].message.content or "").strip()
        usage = getattr(resp, "usage", None)
        tokens = getattr(usage, "total_tokens", 0) if usage else 0
        return _parse_verdict(text, tokens)

    return _critic


def should_escalate(
    confidence: float,
    has_question: bool,
    has_blocking: bool,
    gate_lo: float = DEFAULT_GATE_LO,
    gate_hi: float = DEFAULT_GATE_HI,
) -> bool:
    """Gate logic. True only when the LLM can add signal the deterministic layer lacks."""
    if not has_question:
        return False          # nothing to judge intent against
    if has_blocking:
        return False          # already certain it's wrong; don't pay to confirm
    return gate_lo <= confidence <= gate_hi
