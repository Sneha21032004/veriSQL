# VeriSQL v0.3 — dbt CI Gate + Agent Framework Adapters

Date: 2026-07-07
Status: approved

## Goal

One release, two adoption surfaces, one engine:

1. **`verisql dbt`** — a CI gate that verifies every model in a dbt project for
   silent-failure SQL bugs. dbt teams add one line to CI; no warehouse
   credentials needed for the default parse-only mode.
2. **`verisql.integrations`** — one-import adapters that put the VeriSQL oracle
   inside any agent framework: LangChain, LlamaIndex, OpenAI-compatible
   function calling, and a framework-free decorator.

Positioning: "sqlfluff catches style; VeriSQL catches wrong answers" (dbt side)
and "the deterministic guardrail every SQL agent needs" (agent side).

## Feature A — `verisql dbt`

### CLI

```
verisql dbt --project-dir . [--select model_a model_b]
            [--policy policy.yaml] [--duckdb-path db.duckdb]
            [--warn-only] [--json-out]
```

### Behavior

- Locates `target/manifest.json` under `--project-dir` (or accepts a direct
  `--manifest` path). Manifest is plain JSON; **no dbt dependency added**.
- Pulls each model node (`resource_type == "model"`), preferring
  `compiled_code` (dbt >= 1.3 key) with fallback to `compiled_sql` (older) and
  finally `raw_code`/`raw_sql` with Jinja-aware skip: models whose SQL still
  contains `{{ ... }}` or `{% ... %}` after compilation fallback are reported
  as `SKIPPED (uncompiled)`, never crashed on.
- Maps `metadata.adapter_type` (e.g. `snowflake`, `bigquery`, `postgres`,
  `duckdb`) to the sqlglot dialect; unknown adapters fall back to `duckdb`
  with a note.
- Runs `verisql.verify` per model. Parse-only by default (no connector).
  `--duckdb-path` enables live checks.
- Question/intent checks don't apply (no NL question) — date-coverage etc.
  simply don't fire without a question; this is inherent, not special-cased.

### Output

- Text mode: per-model line `model_name  VERDICT  n flags`, flag detail lines
  beneath failing models, summary footer
  (`N models: X passed, Y review, Z blocked, S skipped`).
- `--json-out`: machine-readable list of per-model reports.
- Exit codes: `2` if any model has blocking (critical) flags, `1` if any
  suggested review, `0` clean. `--warn-only` forces exit `0`.

### Module

`src/verisql/dbt_gate.py`:

- `load_manifest(path) -> dict` — read + validate JSON, clear errors.
- `extract_models(manifest, select) -> list[DbtModel]` — frozen dataclass
  `DbtModel(name, sql, dialect, status)` where status is `ok` / `uncompiled`.
- `verify_project(models, policy, connector) -> DbtGateResult` — runs verify
  per model, aggregates.
- CLI wiring stays thin in `cli.py`.

## Feature B — `verisql.integrations`

New package `src/verisql/integrations/`, all soft imports so the core stays
dependency-light.

### `guard.py` (framework-free, zero new deps)

```python
@sql_guard(connector=db, question_arg="question")
def write_sql(question: str) -> str: ...
```

- Wraps any callable returning SQL. On call: run `verify_and_repair` on the
  returned SQL; return repaired SQL if verified; raise
  `SQLVerificationError(diagnosis, repair_result)` if unfixable.
- `SQLVerificationError` carries the full `RepairResult` so agent loops can
  feed the diagnosis back to the generator.

### `langchain.py`

- `make_verisql_tools(connector=None, dialect="duckdb", policy=None)` returns
  `[verify_sql_tool, fix_sql_tool]` built with `langchain_core.tools.tool`.
  Import of `langchain_core` inside the factory → `ImportError` with
  install hint if missing.

### `llamaindex.py`

- `make_verisql_tools(...)` returning `llama_index.core.tools.FunctionTool`
  pair, same soft-import pattern.

### `openai_tools.py`

- `OPENAI_TOOL_SPECS`: JSON function-calling schemas for `verify_sql` and
  `fix_sql` (works with OpenAI, Groq, Together, vLLM, Ollama — anything
  OpenAI-compatible). Zero dependencies.
- `dispatch_tool_call(name, arguments, connector=None, ...) -> dict` executes
  a tool call and returns the JSON-safe result payload (same shape as the MCP
  server responses).

### Shared internals

- `integrations/_core.py`: `verify_payload(...)` and `fix_payload(...)` —
  the JSON-shaped verify/fix used by openai_tools, langchain, and llamaindex
  wrappers so all surfaces return identical payloads.

## Packaging

`pyproject.toml` extras: `langchain = ["langchain-core>=0.2"]`,
`llamaindex = ["llama-index-core>=0.10"]`. Guard + openai_tools need nothing.

## Testing

- `tests/test_dbt_gate.py`: fixture mini-manifest (2 good models, 1 with
  `NOT IN (NULL)` bug, 1 uncompiled Jinja) → verdicts, select filter, exit
  codes via CliRunner, JSON output shape.
- `tests/test_integrations_guard.py`: decorator returns repaired SQL for
  fixable bug; raises `SQLVerificationError` with diagnosis for unfixable;
  passthrough for clean SQL.
- `tests/test_integrations_openai.py`: schema shape, dispatch round-trip.
- LangChain/LlamaIndex adapters: `pytest.importorskip` — tested only when the
  lib is installed; soft-import error message tested always.
- Existing 102 tests + benchmark gate must stay green.

## Docs

- README: "dbt CI gate" section + "Drop into any agent framework" section,
  roadmap checkbox for dbt hook flipped.
- LAUNCH_KIT: add dbt-community and agent-framework post angles.

## Out of scope (YAGNI)

- GitHub Action wrapper (fast-follow, wraps this CLI).
- dbt package/macros, dbt Cloud API.
- Live-warehouse connectors beyond existing four.
