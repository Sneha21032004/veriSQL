"""The critic is provider-agnostic: any OpenAI-compatible endpoint works, no
Anthropic key required. These tests use fake clients (no network)."""
from types import SimpleNamespace
from verisql import verify, openai_compatible_critic, anthropic_critic
from verisql.critic import CriticRequest


class _FakeOpenAIClient:
    """Mimics openai.OpenAI(...).chat.completions.create(...) shape."""
    def __init__(self, content: str, total_tokens: int = 55):
        message = SimpleNamespace(content=content)
        choice = SimpleNamespace(message=message)
        usage = SimpleNamespace(total_tokens=total_tokens)
        self._resp = SimpleNamespace(choices=[choice], usage=usage)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        return self._resp


class _FakeAnthropicClient:
    def __init__(self, text: str):
        block = SimpleNamespace(text=text)
        usage = SimpleNamespace(input_tokens=80, output_tokens=20)
        self._resp = SimpleNamespace(content=[block], usage=usage)
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        return self._resp


def test_openai_compatible_parses_verdict():
    client = _FakeOpenAIClient('{"agrees": false, "confidence": 0.8, "reason": "no date filter"}')
    critic = openai_compatible_critic("gpt-4o-mini", client=client)
    verdict = critic(CriticRequest(question="q", sql="SELECT 1", dialect="duckdb",
                                   deterministic_confidence=0.6))
    assert verdict.agrees is False
    assert verdict.confidence == 0.8
    assert verdict.tokens_used == 55


def test_anthropic_parses_verdict():
    client = _FakeAnthropicClient('{"agrees": true, "confidence": 0.9, "reason": "ok"}')
    critic = anthropic_critic(client=client)
    verdict = critic(CriticRequest(question="q", sql="SELECT 1", dialect="duckdb",
                                   deterministic_confidence=0.6))
    assert verdict.agrees is True
    assert verdict.tokens_used == 100


def test_local_ollama_style_critic_end_to_end():
    """A free local model (Ollama via OpenAI-compatible API) disagreeing on an
    ambiguous query must surface a critic flag — no paid provider involved."""
    client = _FakeOpenAIClient('{"agrees": false, "confidence": 0.85, "reason": "missing join key"}')
    critic = openai_compatible_critic("qwen2.5-coder:7b", client=client)

    r = verify(
        "SELECT * FROM orders WHERE id != 5",
        question="orders last week excluding id 5",
        dialect="duckdb",
        critic=critic,
    )
    assert r.critic_invoked
    assert any(f.check == "llm_critic" for f in r.flags)


def test_malformed_critic_output_is_safe():
    client = _FakeOpenAIClient("the model rambled without any JSON")
    critic = openai_compatible_critic("gpt-4o-mini", client=client)
    verdict = critic(CriticRequest(question="q", sql="SELECT 1", dialect="duckdb",
                                   deterministic_confidence=0.6))
    # safe default: agrees=True, confidence 0 → never fabricates a disagreement
    assert verdict.agrees is True
    assert verdict.confidence == 0.0
