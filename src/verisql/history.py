"""Query-history learner (Bet 4): catch result-distribution drift over time.

For any tagged query, record (row_count, fingerprint, timestamp). When the same
query runs again, flag if the new row count is >3 sigma from the historical
mean, or > 5x step-change vs the mean.

Storage is a local SQLite file by default, so it works offline; the Postgres
extension's `verisql.history_check` mirrors this server-side.
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DriftReport:
    severity: str          # info | warn | error | none
    message: str
    observed_rows: int
    mean_rows: float | None
    sigma: float | None


class QueryHistory:
    def __init__(self, path: str | Path = "verisql_history.db"):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS history ("
            " tag TEXT NOT NULL, sql_hash TEXT NOT NULL,"
            " fingerprint TEXT NOT NULL, row_count INTEGER NOT NULL,"
            " recorded_at REAL NOT NULL)"
        )
        self._conn.commit()

    @staticmethod
    def _fingerprint(rows: list[tuple]) -> str:
        row_hashes = sorted(
            hashlib.sha256(repr(tuple(str(v) for v in row)).encode()).hexdigest()
            for row in rows
        )
        return hashlib.sha256("".join(row_hashes).encode()).hexdigest()

    def record(self, sql: str, tag: str, connector: Any) -> None:
        rows = connector.execute_readonly(sql, max_rows=10_000)
        self._conn.execute(
            "INSERT INTO history VALUES (?, ?, ?, ?, strftime('%s','now'))",
            (tag, hashlib.md5(sql.encode()).hexdigest(),
             self._fingerprint(rows), len(rows)),
        )
        self._conn.commit()

    def check(self, sql: str, tag: str, connector: Any) -> DriftReport:
        rows = connector.execute_readonly(sql, max_rows=10_000)
        observed = len(rows)

        cur = self._conn.execute(
            "SELECT row_count FROM history WHERE tag = ?", (tag,),
        )
        history = [r[0] for r in cur.fetchall()]
        if not history:
            self.record(sql, tag, connector)
            return DriftReport("info", f"baseline recorded for tag {tag!r}",
                               observed, None, None)

        mean = sum(history) / len(history)
        sigma = math.sqrt(sum((x - mean) ** 2 for x in history) / len(history)) if len(history) > 1 else 0.0

        if sigma > 0 and abs(observed - mean) > 3 * sigma:
            return DriftReport(
                "error",
                f"row-count drift: {observed} now vs mean {mean:.1f} (sigma {sigma:.1f})",
                observed, mean, sigma,
            )
        if mean > 0 and (observed / mean > 5 or mean / max(observed, 1) > 5):
            return DriftReport(
                "warn",
                f"row-count step change: {observed} now vs mean {mean:.1f}",
                observed, mean, sigma,
            )
        return DriftReport("none", "within expected distribution", observed, mean, sigma)

    def close(self) -> None:
        self._conn.close()
