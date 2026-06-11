# Live demo: watch an AI agent self-correct its SQL

5 minutes. You'll run an AI agent against a database with landmines in it, and
watch it catch and fix its own wrong queries by calling the VeriSQL oracle —
no human review, no LLM judging itself.

## Setup (once)

```bash
git clone https://github.com/Sneha21032004/veriSQL.git && cd veriSQL
pip install -e ".[duckdb,mcp]"
python examples/make_demo_db.py        # creates demo_warehouse.duckdb with landmines
```

Open Claude Code in the repo directory. It detects `.mcp.json` and offers to
start the `verisql` MCP server — approve it. (Any MCP-capable agent works the
same way; for others, register `verisql-mcp --duckdb demo_warehouse.duckdb`.)

## The landmines in the demo warehouse

| Trap | Naive AI SQL | Silent result |
|---|---|---|
| `blocklist` contains a NULL | `region NOT IN (SELECT banned_region FROM blocklist)` | **zero rows, always** |
| Orders span Apr–Jun | `SUM(amount) WHERE status='paid'` for "May revenue" | sums all months |
| Timestamps have times | `created_at = '2026-05-03'` | matches nothing (midnight only) |

## Run the demo

Paste into Claude Code:

> Using the demo_warehouse database (tables: customers(id,name,email,region),
> orders(id,customer_id,amount,status,created_at), blocklist(banned_region)):
> answer "Which customers are NOT in a banned region?" — write the SQL, then
> verify it with the verisql fix_sql tool before giving me the answer.
> Show me what the oracle said.

What happens, live:

1. The agent writes the natural query — `... WHERE region NOT IN (SELECT banned_region FROM blocklist)`
2. It calls `fix_sql`. The oracle returns: `not_in_null_subquery` repair, the
   corrected SQL with an `IS NOT NULL` guard, verdict `verified`.
3. The agent runs the corrected SQL and gives the RIGHT answer (3 customers) —
   where the naive query would have silently answered "none."

Then try the others:

> "What was total paid revenue in May 2026?" — verify with verisql before answering.

> "Show orders placed on 2026-05-03." — verify with verisql before answering.

## Why this is the proof

- The bug was real (run the naive SQL yourself: 0 rows).
- The catch was deterministic (AST analysis, same verdict every run, ~2ms, $0).
- The fix was autonomous (no human approved anything; the agent corrected itself).
- The AI did not certify its own output — an independent oracle did. The agent's
  own judgment had approved the broken query; the parser knew better.

That's the difference between "human-in-the-loop verification" (dated) and an
oracle in the agent's loop (how code agents already work — compilers, tests).

## The three tools the agent gets

| Tool | What the agent uses it for |
|---|---|
| `fix_sql` | verify + auto-repair + re-verify; returns corrected SQL |
| `verify_sql` | verdict + diagnosis only (when the agent wants to fix it itself) |
| `diff_sql` | "is my rewrite equivalent to the original?" — migrations, refactors |
