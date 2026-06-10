from verisql import verify, CriticVerdict
from verisql.critic import should_escalate


def test_gate_skips_when_no_question():
    assert should_escalate(confidence=0.6, has_question=False, has_blocking=False) is False


def test_gate_skips_when_confident():
    assert should_escalate(confidence=0.95, has_question=True, has_blocking=False) is False


def test_gate_skips_when_blocking():
    assert should_escalate(confidence=0.6, has_question=True, has_blocking=True) is False


def test_gate_fires_in_band():
    assert should_escalate(confidence=0.6, has_question=True, has_blocking=False) is True


def test_critic_not_called_when_clean():
    """Clean SQL (confidence 1.0) must never spend a critic call."""
    calls = {"n": 0}

    def fake_critic(req):
        calls["n"] += 1
        return CriticVerdict(agrees=True, confidence=1.0, reason="ok", tokens_used=42)

    verify(
        "SELECT SUM(amount) FROM orders WHERE created_at >= '2026-05-01'",
        question="revenue since May",
        dialect="duckdb",
        critic=fake_critic,
    )
    assert calls["n"] == 0


def test_critic_called_in_ambiguous_band():
    calls = {"n": 0}

    def fake_critic(req):
        calls["n"] += 1
        return CriticVerdict(agrees=False, confidence=0.9, reason="missing date filter", tokens_used=37)

    # date_coverage WARN drops confidence to 0.90 — still above gate_hi 0.80.
    # Use a query that accrues a WARN + structural penalty into the band.
    r = verify(
        "SELECT * FROM orders WHERE id != 5",  # filter_required ERROR + null_semantics WARN
        question="orders last week excluding id 5",
        dialect="duckdb",
        critic=fake_critic,
    )
    assert calls["n"] == 1
    assert r.critic_invoked
    assert r.critic_tokens == 37
    assert any(f.check == "llm_critic" for f in r.flags)
