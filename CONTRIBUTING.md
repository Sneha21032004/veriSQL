# Contributing to verisql

Thanks for helping make LLM-generated SQL safe to ship.

## Dev setup

```bash
python -m pip install -e ".[dev]"
pytest -q                      # unit tests + benchmark gate
python -m benchmarks.run_benchmark   # catch-rate report
```

## Project layout

```
src/verisql/
  verify.py            # orchestrator: deterministic-first, gated LLM critic
  report.py            # Report / Flag / Severity
  policy.py            # business-invariant DSL (no dynamic code execution)
  critic.py            # provider-agnostic LLM critic + escalation gate
  checks/              # one file per check; all subclass Check
  connectors/          # duckdb, postgres, snowflake, bigquery adapters
benchmarks/
  corpus.py            # labeled wrong/correct SQL cases
  run_benchmark.py     # measures recall / precision / F1 on live DuckDB
tests/                 # pytest
```

## Adding a check

A check is a small class. Keep it deterministic and free where possible — the
whole value proposition is that we catch bugs without spending LLM tokens.

```python
from verisql.checks.base import Check, CheckContext
from verisql.report import Flag, Report, Severity

class MyCheck(Check):
    name = "my_check"
    requires_connector = False   # True if you need DB access
    requires_ast = True          # True if you need a parsed query

    def run(self, ctx: CheckContext, report: Report) -> None:
        ast = ctx.ast()
        if ast is None:
            return
        # ... inspect ast / ctx.connector ...
        report.add(Flag(check=self.name, severity=Severity.WARN, message="..."))
```

Then register it in `checks/__init__.py` `DEFAULT_CHECKS` (mind the order:
structural/free checks first, execution last).

### Severity guide

| Severity | Use when |
|----------|----------|
| CRITICAL | The query is provably wrong or unsafe (unparseable, cartesian, invariant breach). Blocks. |
| ERROR | Very likely wrong (NOT IN with NULL, timestamp equality, time-scoped question with no date filter). Suggests review. |
| WARN | Suspicious, often intended (`!=` dropping NULLs). Contributes to confidence. |
| INFO | Diagnostic only. |

**Every new check needs a test and, ideally, a labeled case in `benchmarks/corpus.py`.**
The benchmark gate (`MIN_RECALL`, `MIN_PRECISION`) must keep passing.

## Adding a connector

Implement the `Connector` protocol (`list_tables`, `list_columns`,
`execute_readonly`) and optionally `explain` / `column_stats`. Lazy-import the
driver and raise a clear `pip install verisql[<extra>]` hint if missing. Every
read path must be incapable of mutating the target database — guard mutations and,
where the driver supports it, run inside a read-only / rolled-back transaction.

## Adding a critic provider

A critic is any callable `(CriticRequest) -> CriticVerdict`. Prefer wrapping an
existing API; `openai_compatible_critic` already covers OpenAI, Groq, DeepSeek,
Together, Fireworks, OpenRouter, vLLM, and local Ollama. No Anthropic key is
required to use verisql.

## Style

PEP 8, type annotations on public signatures, `ruff check` clean. Keep checks
small and single-purpose.
