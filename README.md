<div align="center">

# VeriSQL

**Audit-grade verification gateway for AI-generated SQL.**

*AI writes your SQL now. VeriSQL proves it didn't lie.*

[![CI](https://github.com/Sneha21032004/veriSQL/actions/workflows/ci.yml/badge.svg)](https://github.com/Sneha21032004/veriSQL/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Recall](https://img.shields.io/badge/silent--failure%20recall-83%25-brightgreen)](#-benchmark-measured-not-claimed)
[![Precision](https://img.shields.io/badge/precision-91%25-brightgreen)](#-benchmark-measured-not-claimed)

</div>

---

## 🧨 The problem

Every BI tool now ships text-to-SQL — Snowflake Cortex Analyst, Databricks Genie, Hex Magic, dbt MCP, Metabase Metabot. The dangerous failures are **not crashes**. They are queries that parse, execute, and return a clean, confident, **wrong** number:

```sql
-- Question: "Total revenue last month"
SELECT SUM(amount) FROM orders WHERE status = 'paid';
-- runs fine, sums ALL TIME → number is 10× too big. Nobody notices for weeks.
```

```sql
-- Question: "Customers not in the banned list"
SELECT * FROM customers WHERE region NOT IN (SELECT banned FROM blocklist);
-- one NULL in blocklist → ALWAYS returns zero rows. Compliance thinks they're clean.
```

An LLM judging its own SQL is non-deterministic, biased toward self-approval, and costs tokens on every call. A regulator will not accept "the model checked itself."

**VeriSQL is the independent, deterministic layer that can.**

## ⚡ What it does

```
            ┌──────────────────────── VeriSQL gateway ───────────────────────┐
AI writes   │  12 deterministic checks      gated LLM critic     audit log   │   human sees
   SQL ───▶ │  (AST · schema · plan ·  ───▶ (only if ambiguous, ─▶ (hash-    │ ──▶ verified
            │   execution · invariants)      any provider)         chained)  │     number
            └─────────────────────────────────────────────────────────────────┘
                     zero LLM tokens              ~10% of queries
```

Three modes, one engine:

| Mode | What it answers | Entry point |
|---|---|---|
| 🔍 **Verify** | "Is this AI-written query silently wrong?" | `verify(...)` / `verisql check` |
| 🧾 **Audit** | "Prove to an auditor what the AI did and what we caught" | `AuditLog` / `verisql audit` |
| 🔁 **Diff** | "Is this LLM-translated query equivalent to the legacy original?" | `verify_equivalence(...)` / `verisql diff` |

## 🚀 Quickstart

```bash
pip install -e ".[duckdb]"   # from a clone (PyPI release pending)
```

```python
from verisql import verify

report = verify(
    sql="SELECT SUM(amount) FROM orders WHERE status = 'paid'",
    question="What was total revenue last month?",
    dialect="snowflake",
)
print(report.summary())
# [ERROR] date_coverage: Question specifies a time range but SQL has no date filter.
# confidence=0.70, review: YES
```

Gate an agent pipeline in four lines:

```python
report = verify(sql, question=q, dialect="snowflake", connector=db, policy=policy)
if report.has_blocking():    reject(report)
elif report.suggested_review: escalate_to_human(report)
else:                         deliver(sql)
```

## 🔍 The checks

All deterministic. All free — **zero LLM tokens**.

| # | Check | Severity | Catches |
|---|---|---|---|
| 1 | `ast_parse` | 🟥 critical | Unparseable SQL |
| 2 | `schema_existence` | 🟥 critical | Hallucinated tables & columns |
| 3 | `cartesian_join` | 🟥 critical | `FROM a, b` with no join key → inflated aggregates |
| 4 | `null_semantics` | 🟧 error / 🟨 warn | `NOT IN (NULL)` → always-empty result; `!=` dropping NULL rows |
| 5 | `timestamp_equality` | 🟧 error | `created_at = '2026-05-01'` matches only exact midnight |
| 6 | `date_coverage` | 🟧 error | Question says "last month", SQL has no date filter |
| 7 | `filter_required` | 🟧 error | Full scan of transactional tables, no WHERE/LIMIT |
| 8 | `explain_plan` | 🟨 warn | Planner chose full scan despite filter (index defeated) — via `EXPLAIN`, never executes |
| 9 | `zero_row_execution` | 🟨 warn | Runs read-only, flags suspicious empty results |
| 10 | `business_invariant` | 🟥 critical | Result violates declared rules (`revenue >= 0`) |
| 11 | `required_filter` | 🟧 error | Policy-governed table queried without mandated filter |
| 12 | `pii_access` | 🟧 error / 🟨 warn | `SELECT *` or PII columns on governed tables (DPDP/GDPR) |

Each flag lowers a confidence score; thresholds decide **deliver / review / reject**.

## 🧾 Audit mode — the compliance artifact

Every verification can land in a **hash-chained, tamper-evident** JSONL log: who asked, which AI generated the SQL, what was flagged, the verdict, and any human override. Edit, insert, or delete a record retroactively → the chain breaks, detectably.

```python
from verisql import verify, AuditLog

log = AuditLog("audit_trail.jsonl")
report = verify(sql, question=q, dialect="snowflake", connector=db, policy=policy)
log.record(report, actor="analyst@firm.in", generator="cortex-analyst")
```

```bash
$ verisql audit --log audit_trail.jsonl
OK: chain intact (1,204 records)

$ verisql audit --log audit_trail.jsonl --evidence
{ "total_verifications": 1204, "decisions": {"delivered": 1031, "review": 158, "rejected": 15},
  "flags_by_check": {"pii_access": 41, "date_coverage": 87, ...}, "chain_valid": true }
```

Built for evidence packs in regulated data teams — RBI / SEBI / DPDP / SOC2 contexts where "the AI touched our numbers" needs provenance.

## 🔁 Diff mode — migration equivalence

Banks migrate Teradata/Oracle → Snowflake/Databricks and use LLMs to translate thousands of queries. Nobody can eyeball 4,000 procs. VeriSQL ranks them:

```bash
$ verisql diff \
    --old-sql "SELECT id FROM orders WHERE status='paid' AND amount>100" \
    --new-sql "SELECT id FROM orders WHERE status='paid'" \
    --old-dialect tsql --new-dialect snowflake

Equivalence verdict: LIKELY_NOT_EQUIVALENT
  [MAJOR] filter: WHERE clauses are not structurally identical after normalization
```

Two independent signals, cheapest first:

1. **Structural diff** *(free, no DB)* — cross-dialect AST normalization catches dropped predicates, changed join types, renamed output columns, altered grouping
2. **Result diff** *(read-only)* — executes both, compares row counts and order-insensitive content hashes on real data

Verdicts — `equivalent · likely_equivalent · likely_not_equivalent · not_equivalent` — sort the batch so humans review only the risky tail.

## 🤖 LLM critic — optional, gated, any provider

Deterministic checks decide ~90% of queries for free. The rest — ambiguous confidence band `[0.4, 0.8]` with a question to judge intent against — can escalate to a cheap LLM critic:

```python
from verisql import verify, openai_compatible_critic

critic = openai_compatible_critic("gpt-4o-mini")                       # OpenAI
critic = openai_compatible_critic("llama-3.1-8b-instant",
            base_url="https://api.groq.com/openai/v1")                 # Groq
critic = openai_compatible_critic("qwen2.5-coder:7b",
            base_url="http://localhost:11434/v1", api_key="ollama")    # local & free

report = verify(sql, question=q, connector=db, critic=critic)
print(report.critic_invoked, report.critic_tokens)
```

**No vendor lock-in**: a critic is any `(CriticRequest) -> CriticVerdict` callable. OpenAI, Groq, DeepSeek, Together, OpenRouter, vLLM, Ollama, or Anthropic (`anthropic_critic`) — your choice. Clean and obviously-broken queries never spend a token.

## 📊 Benchmark — measured, not claimed

`python -m benchmarks.run_benchmark` runs a labeled corpus of wrong + correct queries **live against DuckDB**:

| Metric | Value |
|---|---|
| Recall (silent failures caught) | **83.3%** |
| Precision | **90.9%** |
| F1 | **0.87** |
| False-positive rate | 12.5% |

The misses are `!=`-intent bugs that need the critic tier — the deterministic layer is honest about its limits. The benchmark is a **CI gate** (`tests/test_benchmark_gate.py`): catch-rate cannot silently regress. The labeled corpus grows from real-world misfires — contributions welcome.

## 🔌 Connectors

| Database | Extra | Live checks | Safety mechanism |
|---|---|---|---|
| DuckDB | `[duckdb]` | schema · explain · execute · stats | mutation-keyword guard |
| PostgreSQL | `[postgres]` | schema · explain · execute · `pg_stats` | `BEGIN READ ONLY` + auto `ROLLBACK` |
| Snowflake | `[snowflake]` | schema · `EXPLAIN USING TEXT` · execute | mutation guard |
| BigQuery | `[bigquery]` | schema · **dry-run cost estimate** · execute | `maximum_bytes_billed` cap |

All dialects **parse with zero drivers** — `dialect="snowflake"` etc. runs every structural check without any connection. The verifier is physically incapable of mutating your warehouse.

## 📜 Policy as YAML

```yaml
invariants:
  - "revenue >= 0"
  - "active_users <= total_users"
required_filters:
  transactions: [txn_date]
pii_columns:
  customers: [email, phone, pan_number]
```

```python
from verisql import verify, Policy
report = verify(sql, connector=db, policy=Policy.from_yaml("policy.yaml"))
```

Invariants are parsed by sqlglot and evaluated by a fixed-node walker — **no dynamic code execution, ever**.

## 🗂 Project layout

```
src/verisql/
  verify.py          orchestrator: deterministic-first, gated critic
  audit.py           hash-chained tamper-evident audit log
  equivalence.py     migration equivalence verifier
  policy.py          invariants + governance rules (YAML)
  critic.py          provider-agnostic LLM escalation
  checks/            12 checks, one file each
  connectors/        duckdb · postgres · snowflake · bigquery
benchmarks/          labeled corpus + live catch-rate harness (CI gate)
examples/            quickstart · agent_loop · compliance_gateway
```

## 🧭 Roadmap

- [x] 12 deterministic checks, 4 connectors, policy DSL, gated multi-provider critic
- [x] Tamper-evident audit trail + evidence packs
- [x] Migration equivalence verifier (structural + data)
- [ ] Bulk diff runner (`verisql diff --batch manifest.csv`) for 1000s of migration queries
- [ ] Corpus expansion from Spider/BIRD + real-world misfires
- [ ] dbt / Hex / Snowflake Cortex integration hooks
- [ ] Column-stats aggregate-range sanity checks

## 🤝 Contributing

New checks, connectors, and labeled wrong-SQL cases are the most valuable contributions — see [CONTRIBUTING.md](CONTRIBUTING.md). Every check needs a test; the benchmark gate must keep passing.

## 📄 License

[MIT](LICENSE)

---

<div align="center">
<i>The AI cannot certify its own output. Something independent has to.</i>
</div>
