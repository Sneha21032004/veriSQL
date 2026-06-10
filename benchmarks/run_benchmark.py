"""Measure verisql catch-rate against the labeled corpus, live on DuckDB.

A query is "flagged" by verisql if it produces a blocking flag OR a review is
suggested. We compare that to the ground-truth label.

    recall        = flagged wrong / all wrong         (silent failures caught)
    false_pos_rate = flagged correct / all correct    (good queries wrongly stopped)
    precision     = flagged wrong / all flagged

Run:  python benchmarks/run_benchmark.py
Exit code is non-zero if recall or precision fall below the gate thresholds.
"""
import sys

import duckdb

from verisql import verify, Policy
from verisql.connectors.duckdb_conn import DuckDBConnector
from benchmarks.corpus import CASES, SCHEMA_SQL

# gate thresholds for CI — tune as the corpus grows
MIN_RECALL = 0.80
MIN_PRECISION = 0.80

# Core benchmark uses only a value invariant. required_filters is an opt-in
# enterprise guardrail that intentionally trades false positives for coverage on
# governed tables; measuring it here would conflate policy strictness with the
# intrinsic quality of the deterministic checks.
POLICY = Policy(invariants=["amount >= 0"])


def _flagged(report) -> bool:
    return report.has_blocking() or report.suggested_review


def run() -> int:
    conn = duckdb.connect(":memory:")
    conn.execute(SCHEMA_SQL)
    db = DuckDBConnector(conn)

    tp = fp = tn = fn = 0
    missed: list[str] = []
    false_alarms: list[str] = []

    for case in CASES:
        report = verify(
            case.sql, question=case.question, dialect="duckdb",
            connector=db, policy=POLICY,
        )
        flagged = _flagged(report)
        is_wrong = case.label == "wrong"

        if is_wrong and flagged:
            tp += 1
        elif is_wrong and not flagged:
            fn += 1
            missed.append(f"{case.bug}: {case.question}")
        elif not is_wrong and flagged:
            fp += 1
            top = next((f.message for f in report.flags), "?")
            false_alarms.append(f"{case.question} -> {top}")
        else:
            tn += 1

    wrong_n = tp + fn
    correct_n = tn + fp
    recall = tp / wrong_n if wrong_n else 0.0
    fpr = fp / correct_n if correct_n else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    print("=" * 60)
    print("verisql benchmark (DuckDB, live)")
    print("=" * 60)
    print(f"  cases           : {len(CASES)}  ({wrong_n} wrong, {correct_n} correct)")
    print(f"  recall          : {recall:.1%}   (silent failures caught)")
    print(f"  false-pos rate  : {fpr:.1%}   (good queries wrongly stopped)")
    print(f"  precision       : {precision:.1%}")
    print(f"  F1              : {f1:.2f}")
    print(f"  confusion       : TP={tp} FP={fp} TN={tn} FN={fn}")

    if missed:
        print("\n  MISSED wrong queries:")
        for m in missed:
            print(f"    - {m}")
    if false_alarms:
        print("\n  FALSE ALARMS on correct queries:")
        for fa in false_alarms:
            print(f"    - {fa}")

    ok = recall >= MIN_RECALL and precision >= MIN_PRECISION
    print("\n  RESULT:", "PASS" if ok else "FAIL",
          f"(need recall>={MIN_RECALL:.0%}, precision>={MIN_PRECISION:.0%})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
