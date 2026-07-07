"""dbt CI gate: verify every model in a dbt project for silent-failure SQL bugs.

sqlfluff catches style; this catches wrong answers. The gate reads dbt's
compiled `target/manifest.json` — plain JSON, so there is **no dbt dependency**
and it works with any dbt version that produces a manifest. Parse-only by
default: no warehouse credentials needed, which makes it a one-line add to any
CI pipeline. Pass a connector for live schema/plan/execution checks.

    verisql dbt --project-dir .           # after `dbt compile` / `dbt build`
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verisql.verify import verify

# adapter_type values from dbt manifests -> sqlglot dialect names
_ADAPTER_DIALECTS = {
    "duckdb": "duckdb",
    "postgres": "postgres",
    "redshift": "redshift",
    "snowflake": "snowflake",
    "bigquery": "bigquery",
    "databricks": "databricks",
    "spark": "spark",
    "trino": "trino",
    "sqlserver": "tsql",
    "mysql": "mysql",
}
_DEFAULT_DIALECT = "duckdb"

_JINJA_PATTERN = re.compile(r"{{.*?}}|{%.*?%}", re.DOTALL)


@dataclass(frozen=True)
class DbtModel:
    name: str
    sql: str
    dialect: str
    status: str  # "ok" | "uncompiled"


@dataclass(frozen=True)
class ModelResult:
    model: str
    verdict: str  # "passed" | "review" | "blocked" | "skipped"
    confidence: float
    flags: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class DbtGateResult:
    model_results: list[ModelResult]

    @property
    def total(self) -> int:
        return len(self.model_results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.model_results if r.verdict == "passed")

    @property
    def review(self) -> int:
        return sum(1 for r in self.model_results if r.verdict == "review")

    @property
    def blocked(self) -> int:
        return sum(1 for r in self.model_results if r.verdict == "blocked")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.model_results if r.verdict == "skipped")

    def summary(self) -> str:
        return (
            f"{self.total} model(s): {self.passed} passed, {self.review} review, "
            f"{self.blocked} blocked, {self.skipped} skipped"
        )

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "review": self.review,
            "blocked": self.blocked,
            "skipped": self.skipped,
            "models": [
                {
                    "model": r.model,
                    "verdict": r.verdict,
                    "confidence": round(r.confidence, 2),
                    "flags": r.flags,
                }
                for r in self.model_results
            ],
        }


def find_manifest(project_dir: str | Path) -> Path:
    """Return the manifest path for a dbt project directory."""
    path = Path(project_dir) / "target" / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No manifest at {path}. Run `dbt compile` (or `dbt build`) first, "
            "or pass --manifest with an explicit path."
        )
    return path


def load_manifest(path: str | Path) -> dict:
    """Read and parse a dbt manifest.json with clear failure messages."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Manifest at {path} is not valid JSON: {e}") from e


def _model_sql(node: dict) -> tuple[str, str]:
    """Return (sql, status) preferring compiled code over raw Jinja source."""
    for key in ("compiled_code", "compiled_sql"):
        sql = node.get(key)
        if sql:
            return sql, "ok"
    for key in ("raw_code", "raw_sql"):
        sql = node.get(key)
        if sql:
            status = "uncompiled" if _JINJA_PATTERN.search(sql) else "ok"
            return sql, status
    return "", "uncompiled"


def extract_models(manifest: dict, select: list[str] | None = None) -> list[DbtModel]:
    """Pull verifiable models out of a parsed manifest."""
    adapter = (manifest.get("metadata") or {}).get("adapter_type", "")
    dialect = _ADAPTER_DIALECTS.get(adapter, _DEFAULT_DIALECT)

    models: list[DbtModel] = []
    for node in (manifest.get("nodes") or {}).values():
        if node.get("resource_type") != "model":
            continue
        name = node.get("name", "<unnamed>")
        if select and name not in select:
            continue
        sql, status = _model_sql(node)
        models.append(DbtModel(name=name, sql=sql, dialect=dialect, status=status))
    return models


def verify_project(
    models: list[DbtModel],
    policy: Any = None,
    connector: Any = None,
) -> DbtGateResult:
    """Run VeriSQL's deterministic checks against every model."""
    results: list[ModelResult] = []
    for model in models:
        if model.status == "uncompiled":
            results.append(ModelResult(model=model.name, verdict="skipped", confidence=0.0))
            continue

        report = verify(model.sql, dialect=model.dialect, connector=connector, policy=policy)
        if report.has_blocking():
            verdict = "blocked"
        elif report.suggested_review:
            verdict = "review"
        else:
            verdict = "passed"
        results.append(ModelResult(
            model=model.name,
            verdict=verdict,
            confidence=report.confidence,
            flags=[
                {"check": f.check, "severity": f.severity.value, "message": f.message}
                for f in report.flags
            ],
        ))
    return DbtGateResult(model_results=results)


def render_text(result: DbtGateResult) -> str:
    """Human-readable per-model report for CI logs."""
    width = max((len(r.model) for r in result.model_results), default=10)
    lines = []
    for r in result.model_results:
        marker = {"passed": "PASS", "review": "WARN", "blocked": "FAIL", "skipped": "SKIP"}[r.verdict]
        lines.append(f"  {marker}  {r.model.ljust(width)}  {r.verdict}  ({len(r.flags)} flag(s))")
        for f in r.flags:
            lines.append(f"          [{f['severity'].upper()}] {f['check']}: {f['message']}")
    lines.append(result.summary())
    return "\n".join(lines)
