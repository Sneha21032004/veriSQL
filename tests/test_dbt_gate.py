"""Tests for the dbt CI gate: manifest parsing, per-model verification, CLI."""
import json

import pytest
from click.testing import CliRunner

from verisql.cli import main
from verisql.dbt_gate import DbtModel, extract_models, load_manifest, verify_project


def make_manifest(tmp_path, models):
    """Write a minimal dbt manifest.json and return its path."""
    manifest = {
        "metadata": {"adapter_type": "duckdb", "dbt_version": "1.7.0"},
        "nodes": {
            f"model.proj.{name}": {
                "resource_type": "model",
                "name": name,
                "compiled_code": sql,
            }
            for name, sql in models.items()
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


GOOD_SQL = "SELECT id, amount FROM orders WHERE status = 'paid' AND order_date >= '2026-01-01'"
NULL_BUG_SQL = "SELECT * FROM customers WHERE id NOT IN (1, NULL)"
JINJA_SQL = "SELECT * FROM {{ ref('orders') }}"


# --------------------------------------------------------------------------- #
# manifest loading + model extraction
# --------------------------------------------------------------------------- #

def test_load_manifest_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "nope" / "manifest.json")


def test_load_manifest_invalid_json_raises(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_manifest(bad)


def test_extract_models_pulls_compiled_code(tmp_path):
    path = make_manifest(tmp_path, {"good_model": GOOD_SQL})
    models = extract_models(load_manifest(path))
    assert len(models) == 1
    assert models[0].name == "good_model"
    assert models[0].sql == GOOD_SQL
    assert models[0].dialect == "duckdb"
    assert models[0].status == "ok"


def test_extract_models_skips_non_model_nodes(tmp_path):
    manifest = {
        "metadata": {"adapter_type": "duckdb"},
        "nodes": {
            "test.proj.a_test": {"resource_type": "test", "name": "a_test", "compiled_code": "SELECT 1"},
            "model.proj.m": {"resource_type": "model", "name": "m", "compiled_code": GOOD_SQL},
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    models = extract_models(load_manifest(path))
    assert [m.name for m in models] == ["m"]


def test_extract_models_marks_uncompiled_jinja(tmp_path):
    manifest = {
        "metadata": {"adapter_type": "duckdb"},
        "nodes": {
            "model.proj.raw_only": {"resource_type": "model", "name": "raw_only", "raw_code": JINJA_SQL},
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    models = extract_models(load_manifest(path))
    assert models[0].status == "uncompiled"


def test_extract_models_select_filter(tmp_path):
    path = make_manifest(tmp_path, {"a": GOOD_SQL, "b": GOOD_SQL})
    models = extract_models(load_manifest(path), select=["b"])
    assert [m.name for m in models] == ["b"]


def test_extract_models_maps_adapter_to_dialect(tmp_path):
    manifest = {
        "metadata": {"adapter_type": "snowflake"},
        "nodes": {
            "model.proj.m": {"resource_type": "model", "name": "m", "compiled_code": GOOD_SQL},
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    models = extract_models(load_manifest(path))
    assert models[0].dialect == "snowflake"


def test_extract_models_unknown_adapter_falls_back(tmp_path):
    manifest = {
        "metadata": {"adapter_type": "exoticdb"},
        "nodes": {
            "model.proj.m": {"resource_type": "model", "name": "m", "compiled_code": GOOD_SQL},
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    models = extract_models(load_manifest(path))
    assert models[0].dialect == "duckdb"


# --------------------------------------------------------------------------- #
# project verification
# --------------------------------------------------------------------------- #

def test_verify_project_catches_null_bug(tmp_path):
    path = make_manifest(tmp_path, {"good": GOOD_SQL, "bad": NULL_BUG_SQL})
    result = verify_project(extract_models(load_manifest(path)))
    by_name = {r.model: r for r in result.model_results}
    assert by_name["good"].verdict == "passed"
    assert by_name["bad"].verdict in ("review", "blocked")
    assert any("null" in f["check"] or "null" in f["message"].lower()
               for f in by_name["bad"].flags)


def test_verify_project_counts(tmp_path):
    path = make_manifest(tmp_path, {"good": GOOD_SQL, "bad": NULL_BUG_SQL})
    result = verify_project(extract_models(load_manifest(path)))
    assert result.total == 2
    assert result.passed == 1
    assert result.review + result.blocked == 1


def test_verify_project_skips_uncompiled():
    models = [DbtModel(name="j", sql=JINJA_SQL, dialect="duckdb", status="uncompiled")]
    result = verify_project(models)
    assert result.skipped == 1
    assert result.model_results[0].verdict == "skipped"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def test_cli_dbt_clean_project_exits_zero(tmp_path):
    (tmp_path / "target").mkdir()
    make_manifest(tmp_path / "target", {"good": GOOD_SQL})
    runner = CliRunner()
    res = runner.invoke(main, ["dbt", "--project-dir", str(tmp_path)])
    assert res.exit_code == 0
    assert "good" in res.output
    assert "passed" in res.output.lower()


def test_cli_dbt_bad_model_fails_ci(tmp_path):
    (tmp_path / "target").mkdir()
    make_manifest(tmp_path / "target", {"bad": NULL_BUG_SQL})
    runner = CliRunner()
    res = runner.invoke(main, ["dbt", "--project-dir", str(tmp_path)])
    assert res.exit_code in (1, 2)
    assert "bad" in res.output


def test_cli_dbt_warn_only_forces_zero(tmp_path):
    (tmp_path / "target").mkdir()
    make_manifest(tmp_path / "target", {"bad": NULL_BUG_SQL})
    runner = CliRunner()
    res = runner.invoke(main, ["dbt", "--project-dir", str(tmp_path), "--warn-only"])
    assert res.exit_code == 0


def test_cli_dbt_json_output(tmp_path):
    (tmp_path / "target").mkdir()
    make_manifest(tmp_path / "target", {"good": GOOD_SQL, "bad": NULL_BUG_SQL})
    runner = CliRunner()
    res = runner.invoke(main, ["dbt", "--project-dir", str(tmp_path), "--json-out"])
    payload = json.loads(res.output)
    assert payload["total"] == 2
    names = {m["model"] for m in payload["models"]}
    assert names == {"good", "bad"}


def test_cli_dbt_missing_manifest_clear_error(tmp_path):
    runner = CliRunner()
    res = runner.invoke(main, ["dbt", "--project-dir", str(tmp_path)])
    assert res.exit_code == 2
    assert "manifest" in res.output.lower()


def test_cli_dbt_select_filter(tmp_path):
    (tmp_path / "target").mkdir()
    make_manifest(tmp_path / "target", {"good": GOOD_SQL, "bad": NULL_BUG_SQL})
    runner = CliRunner()
    res = runner.invoke(main, ["dbt", "--project-dir", str(tmp_path), "--select", "good"])
    assert res.exit_code == 0
    assert "bad" not in res.output
