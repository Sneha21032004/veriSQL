"""Tamper-evident audit trail for AI-generated SQL verification.

Each verification produces one AuditRecord. Records are appended to a JSONL file
and hash-chained: every record carries the SHA-256 of the previous record, so any
retroactive edit breaks the chain and is detectable with `verify_chain()`.

This is the compliance artifact: who asked, what the AI wrote, what was checked,
what the verdict was, and who (if anyone) overrode it. Designed for audit-evidence
packs in regulated data teams (RBI / SEBI / DPDP / SOC2 contexts).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from verisql.report import Report

GENESIS_HASH = "0" * 64


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _canonical(payload: dict[str, Any]) -> str:
    """Deterministic JSON serialization — stable across runs for hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class AuditRecord:
    # provenance
    timestamp: str
    actor: str                      # human or service that requested the query
    generator: str                  # which AI produced the SQL (model/tool name)
    question: str | None
    sql: str
    sql_sha256: str
    dialect: str
    # verification outcome
    confidence: float
    flags: list[dict[str, Any]]
    suggested_review: bool
    blocking: bool
    decision: str                   # delivered | review | rejected | overridden
    override_by: str | None = None
    override_reason: str | None = None
    # chain
    prev_hash: str = GENESIS_HASH
    record_hash: str = ""

    def compute_hash(self) -> str:
        payload = asdict(self)
        payload.pop("record_hash", None)
        return _sha256(_canonical(payload))

    def seal(self, prev_hash: str) -> "AuditRecord":
        self.prev_hash = prev_hash
        self.record_hash = self.compute_hash()
        return self


@dataclass
class ChainStatus:
    valid: bool
    records: int
    first_bad_index: int | None = None
    reason: str | None = None


class AuditLog:
    """Append-only, hash-chained JSONL audit log."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- write ---------------------------------------------------------------

    def record(
        self,
        report: Report,
        actor: str,
        generator: str = "unknown",
        decision: str | None = None,
        override_by: str | None = None,
        override_reason: str | None = None,
    ) -> AuditRecord:
        """Create, seal, and append an audit record for a verification report."""
        if decision is None:
            if report.has_blocking():
                decision = "rejected"
            elif report.suggested_review:
                decision = "review"
            else:
                decision = "delivered"

        rec = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            generator=generator,
            question=report.question,
            sql=report.sql,
            sql_sha256=_sha256(report.sql),
            dialect=report.dialect,
            confidence=report.confidence,
            flags=[f.model_dump() for f in report.flags],
            suggested_review=report.suggested_review,
            blocking=report.has_blocking(),
            decision=decision,
            override_by=override_by,
            override_reason=override_reason,
        )
        rec.seal(self._last_hash())
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(_canonical(asdict(rec)) + "\n")
        return rec

    # -- read / verify ---------------------------------------------------------

    def _last_hash(self) -> str:
        last = None
        for last in self.iter_records():
            pass
        return last["record_hash"] if last else GENESIS_HASH

    def iter_records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def verify_chain(self) -> ChainStatus:
        """Walk the chain; detect any tampered, inserted, or deleted record."""
        prev = GENESIS_HASH
        count = 0
        for i, raw in enumerate(self.iter_records()):
            count += 1
            stored_hash = raw.get("record_hash", "")
            if raw.get("prev_hash") != prev:
                return ChainStatus(False, count, i, "prev_hash mismatch (insertion/deletion)")
            payload = dict(raw)
            payload.pop("record_hash", None)
            if _sha256(_canonical(payload)) != stored_hash:
                return ChainStatus(False, count, i, "record content altered")
            prev = stored_hash
        return ChainStatus(True, count)

    def evidence_pack(self) -> dict[str, Any]:
        """Summary for an audit evidence submission: volumes, outcomes, chain health."""
        decisions: dict[str, int] = {}
        flagged_checks: dict[str, int] = {}
        total = 0
        for raw in self.iter_records():
            total += 1
            decisions[raw["decision"]] = decisions.get(raw["decision"], 0) + 1
            for fl in raw.get("flags", []):
                name = fl.get("check", "?")
                flagged_checks[name] = flagged_checks.get(name, 0) + 1
        chain = self.verify_chain()
        return {
            "total_verifications": total,
            "decisions": decisions,
            "flags_by_check": flagged_checks,
            "chain_valid": chain.valid,
            "chain_records": chain.records,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "log_file": str(self.path),
        }
