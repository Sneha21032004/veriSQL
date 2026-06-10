import json

from verisql import verify, AuditLog


def _verify_and_record(log, sql, question=None, **kw):
    report = verify(sql, question=question, dialect="duckdb")
    return log.record(report, actor="analyst@firm.in", generator="cortex-analyst", **kw)


def test_records_append_and_chain_valid(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    _verify_and_record(log, "SELECT 1 AS x")
    _verify_and_record(log, "SELECT * FROM orders", question="all orders")
    _verify_and_record(log, "SELECT * FROM a, b")  # cartesian -> rejected

    status = log.verify_chain()
    assert status.valid
    assert status.records == 3


def test_decision_auto_classification(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    clean = _verify_and_record(log, "SELECT 1 AS x")
    rejected = _verify_and_record(log, "SELECT * FROM a, b")
    assert clean.decision == "delivered"
    assert rejected.decision == "rejected"


def test_override_recorded(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    rec = _verify_and_record(
        log, "SELECT * FROM orders",
        decision="overridden", override_by="cdo@firm.in",
        override_reason="ad-hoc regulator request, reviewed manually",
    )
    assert rec.decision == "overridden"
    assert rec.override_by == "cdo@firm.in"


def test_tampering_detected_content_edit(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    _verify_and_record(log, "SELECT 1 AS x")
    _verify_and_record(log, "SELECT 2 AS y")

    # attacker edits the SQL of record 0 after the fact
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    rec0 = json.loads(lines[0])
    rec0["sql"] = "SELECT 999 AS x"
    lines[0] = json.dumps(rec0, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    status = AuditLog(path).verify_chain()
    assert not status.valid
    assert status.first_bad_index == 0
    assert "altered" in status.reason


def test_tampering_detected_record_deletion(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    _verify_and_record(log, "SELECT 1 AS x")
    _verify_and_record(log, "SELECT 2 AS y")
    _verify_and_record(log, "SELECT 3 AS z")

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    del lines[1]  # delete the middle record
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    status = AuditLog(path).verify_chain()
    assert not status.valid
    assert "prev_hash" in status.reason


def test_evidence_pack_summary(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    _verify_and_record(log, "SELECT 1 AS x")
    _verify_and_record(log, "SELECT * FROM a, b")
    pack = log.evidence_pack()
    assert pack["total_verifications"] == 2
    assert pack["chain_valid"] is True
    assert pack["decisions"].get("delivered") == 1
    assert pack["decisions"].get("rejected") == 1
