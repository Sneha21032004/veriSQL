# VeriSQL Launch Kit

Ready-to-paste posts for each channel. Post in this order; each builds on the last.

---

## 1. Hacker News (Show HN) — highest leverage, post Tue-Thu 8-10am US Eastern

**Title (pick one):**

> Show HN: VeriSQL – deterministic verify-and-repair for AI-generated SQL

> Show HN: SQL has no compiler error for "wrong answer" – so I built one

**Body:**

AI writes SQL everywhere now (Cortex Analyst, Genie, ChatGPT, internal bots). The dangerous failures aren't crashes — the query parses, runs, and returns a confident wrong number.

Classic example: `WHERE id NOT IN (SELECT banned_id FROM blocklist)` — one NULL in the blocklist and the query returns zero rows, always, by SQL's three-valued logic. The dashboard says "0 banned customers." Compliance thinks they're clean.

LLM-as-judge approves that query most of the time (self-preference bias, non-determinism). So I built the deterministic alternative: VeriSQL parses the SQL into an AST, runs 12 checks (NULL semantics, cartesian joins, timestamp-equality-vs-range, schema existence, query-plan sanity, business invariants), and — this is the new part — auto-repairs the fixable bugs with provably-correct AST rewrites, then re-verifies. No LLM tokens for any of it.

It also keeps a hash-chained audit log (who asked, what the AI wrote, what was fixed) and has an equivalence mode for verifying LLM-translated queries during warehouse migrations.

Measured on a labeled corpus, live against DuckDB: 83% recall on silent failures, 91% precision. The benchmark is a CI gate so the numbers can't silently regress.

Python, MIT, works with DuckDB/Postgres/Snowflake/BigQuery. Honest limitation: intent-level bugs (`!=` the user didn't mean) still need an LLM critic tier — that part is pluggable and gated to ambiguous cases only.

https://github.com/Sneha21032004/veriSQL

**HN rules:** reply to every comment fast, especially critical ones. Concede valid criticism immediately — HN rewards honesty. Do NOT ask friends to upvote (vote-ring detection kills posts).

---

## 2. Reddit r/dataengineering

**Title:**

> Built an open-source tool that catches (and auto-fixes) silently-wrong AI-generated SQL — the NOT IN (NULL) class of bugs

**Body:**

Every text-to-SQL tool I've used has the same failure mode: the query runs fine and returns a plausible wrong number. Missing date filter sums all-time revenue. `NOT IN` with a NULL returns zero rows forever. Comma-join cartesian inflates aggregates 5x.

I got tired of being the human who debugs these after the CFO saw the number, so I built VeriSQL: deterministic AST checks (sqlglot), auto-repair via tree rewrites, read-only execution probes, and a tamper-evident audit log for the "what did the AI touch" compliance question.

83% recall / 91% precision on a labeled benchmark that runs live in CI. MIT licensed. Would love to hear which silent failures you've been bitten by — building the corpus from real misfires.

(also post to: r/Python, r/SQL, r/LocalLLaMA — adjust first line per sub)

---

## 3. Twitter/X thread

**Tweet 1:**
AI writes your SQL now. Here's the problem nobody talks about:

`WHERE id NOT IN (SELECT banned_id FROM blocklist)`

One NULL in that blocklist → query returns ZERO rows. Always. Silently.

Your dashboard says "0 banned users." It's lying.

**Tweet 2:**
This isn't rare. It's SQL three-valued logic. And LLM-judges approve this query ~70% of the time (they share the same blind spot).

A compiler would catch this. SQL has no compiler error for "wrong answer."

**Tweet 3:**
So I built one. VeriSQL: 12 deterministic AST checks + auto-repair.

It doesn't flag the bug for a human. It REWRITES the query (provably-correct tree transform), re-verifies, ships. 2ms. $0. No LLM.

**Tweet 4:**
Measured, not claimed: 83% recall on silent failures, 91% precision, benchmark runs live in CI as a regression gate.

Python · MIT · DuckDB/Postgres/Snowflake/BigQuery

[repo link]

---

## 4. LinkedIn (your network + Hemant's)

The "AI wrote our SQL and the number was wrong for 3 weeks" story is becoming universal in data teams.

I open-sourced VeriSQL — a deterministic verify-and-repair layer for AI-generated SQL. Think of it as the compiler+test-suite the data layer never had: it catches the queries that run fine but answer the wrong question (NULL semantics, cartesian joins, missing date scopes), auto-fixes the deterministic ones with AST rewrites, and keeps a tamper-evident audit trail for compliance.

83% recall / 91% precision on a live benchmark. MIT licensed. Link in comments.

---

## 5. Submission targets (free distribution)

- [ ] Hacker News (Show HN)
- [ ] r/dataengineering, r/Python, r/SQL, r/LocalLLaMA
- [ ] Awesome lists via PR: `awesome-llm`, `awesome-text-to-sql`, `awesome-data-engineering`, `awesome-python`
- [ ] Python Weekly + Data Engineering Weekly newsletters (submission forms)
- [ ] dev.to / Hashnode crosspost of the NOT IN (NULL) story
- [ ] Lobste.rs (needs invite)
- [ ] Product Hunt (later — after GitHub traction, not before)

## 6. The blog post that does SEO work

Title: **"Your AI's SQL is lying to you: the NOT IN (NULL) bug every text-to-SQL tool ships"**

This is the searchable artifact. Target keywords: "text-to-sql wrong results", "AI SQL verification", "NOT IN NULL returns no rows", "LLM SQL hallucination". Post on dev.to + your own blog, link to repo. Evergreen search traffic > launch spike.

## 7. Timing plan

- Day 0: polish repo (done), pin repo to profile, set About/topics (done)
- Day 1: blog post live → tweet thread → LinkedIn
- Day 2: Show HN at 8-10am ET Tue/Wed/Thu + Reddit r/dataengineering same morning
- Day 3-4: remaining subreddits, awesome-list PRs, newsletter submissions
- Day 7: write follow-up: "What 500 people told me about their AI SQL failures" → second wave

## 8. Honest expectations

- HN front page: 300–2,000 stars in 48h. Miss: 20–100.
- 50k stars = top-20-of-all-time territory; nothing guarantees it. Compounding path: launch spike → newsletter pickups → awesome lists → search traffic → steady growth.
- The single biggest star-driver you control: a 20-second terminal GIF of `verisql fix` at the top of the README. Record with [asciinema](https://asciinema.org) or [vhs](https://github.com/charmbracelet/vhs).
