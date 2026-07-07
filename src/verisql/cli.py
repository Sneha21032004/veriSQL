import json
import sys
import click
from verisql import verify


@click.group()
def main() -> None:
    """verisql — runtime verifier for LLM-generated SQL."""


@main.command()
@click.option("--sql", required=True, help="SQL string to verify (or - to read stdin).")
@click.option("--question", default=None, help="Natural-language question that produced the SQL.")
@click.option("--dialect", default="duckdb", help="sqlglot dialect (default: duckdb).")
@click.option("--duckdb-path", default=None, help="Path to a DuckDB file for live checks.")
@click.option("--postgres-dsn", default=None, help="Postgres DSN for live checks.")
@click.option("--policy", "policy_path", default=None, help="Path to a policy YAML file.")
@click.option("--json-out", is_flag=True, help="Emit JSON report instead of text summary.")
def check(
    sql: str,
    question: str | None,
    dialect: str,
    duckdb_path: str | None,
    postgres_dsn: str | None,
    policy_path: str | None,
    json_out: bool,
) -> None:
    """Verify a single SQL statement."""
    if sql == "-":
        sql = sys.stdin.read()

    connector = None
    if duckdb_path:
        from verisql.connectors.duckdb_conn import DuckDBConnector
        connector = DuckDBConnector.from_path(duckdb_path)
    elif postgres_dsn:
        from verisql.connectors.postgres_conn import PostgresConnector
        connector = PostgresConnector.from_dsn(postgres_dsn)

    policy = None
    if policy_path:
        from verisql.policy import Policy
        policy = Policy.from_yaml(policy_path)

    report = verify(sql, question=question, dialect=dialect, connector=connector, policy=policy)

    if json_out:
        click.echo(report.model_dump_json(indent=2))
    else:
        click.echo(report.summary())

    sys.exit(2 if report.has_blocking() else (1 if report.suggested_review else 0))


@main.command()
@click.option("--old-sql", required=True, help="Legacy/original SQL.")
@click.option("--new-sql", required=True, help="Translated/rewritten SQL.")
@click.option("--old-dialect", default="duckdb", help="Dialect of the legacy SQL.")
@click.option("--new-dialect", default=None, help="Dialect of the new SQL (defaults to old).")
@click.option("--duckdb-path", default=None, help="DuckDB file to run the result diff against.")
@click.option("--json-out", is_flag=True, help="Emit JSON instead of text summary.")
def diff(old_sql: str, new_sql: str, old_dialect: str, new_dialect: str | None,
         duckdb_path: str | None, json_out: bool) -> None:
    """Verify a migrated/rewritten query is equivalent to the original."""
    import dataclasses
    import json as _json
    from verisql.equivalence import verify_equivalence

    connector = None
    if duckdb_path:
        from verisql.connectors.duckdb_conn import DuckDBConnector
        connector = DuckDBConnector.from_path(duckdb_path)

    report = verify_equivalence(
        old_sql, new_sql, old_dialect=old_dialect,
        new_dialect=new_dialect, connector=connector,
    )
    if json_out:
        click.echo(_json.dumps(dataclasses.asdict(report), indent=2, default=str))
    else:
        click.echo(report.summary())
    sys.exit(0 if report.verdict in ("equivalent", "likely_equivalent") else 1)


@main.command()
@click.option("--log", "log_path", required=True, help="Path to the audit JSONL log.")
@click.option("--evidence", is_flag=True, help="Print an evidence-pack summary instead of chain check.")
def audit(log_path: str, evidence: bool) -> None:
    """Verify audit-chain integrity or produce an evidence-pack summary."""
    import json as _json
    from verisql.audit import AuditLog

    log = AuditLog(log_path)
    if evidence:
        click.echo(_json.dumps(log.evidence_pack(), indent=2))
        return
    status = log.verify_chain()
    if status.valid:
        click.echo(f"OK: chain intact ({status.records} records)")
        sys.exit(0)
    click.echo(f"TAMPERED: {status.reason} at record index {status.first_bad_index}")
    sys.exit(2)


@main.command()
@click.option("--sql", required=True, help="AI-generated SQL to verify and auto-repair.")
@click.option("--question", default=None, help="The natural-language question behind the SQL.")
@click.option("--dialect", default="duckdb", help="sqlglot dialect.")
@click.option("--duckdb-path", default=None, help="DuckDB file for live verification.")
def fix(sql: str, question: str | None, dialect: str, duckdb_path: str | None) -> None:
    """Verify, auto-repair, and re-verify a query. Prints the corrected SQL."""
    from verisql.repair import verify_and_repair

    connector = None
    if duckdb_path:
        from verisql.connectors.duckdb_conn import DuckDBConnector
        connector = DuckDBConnector.from_path(duckdb_path)

    result = verify_and_repair(sql, question=question, dialect=dialect, connector=connector)
    click.echo(result.summary())
    click.echo("\n--- final SQL ---")
    click.echo(result.final_sql)
    sys.exit(0 if result.verified else 1)


@main.command()
@click.option("--project-dir", default=".", help="dbt project directory (containing target/manifest.json).")
@click.option("--manifest", "manifest_path", default=None, help="Explicit path to manifest.json (overrides --project-dir).")
@click.option("--select", multiple=True, help="Only verify these model names (repeatable).")
@click.option("--policy", "policy_path", default=None, help="Path to a policy YAML file.")
@click.option("--duckdb-path", default=None, help="DuckDB file for live checks (default is parse-only).")
@click.option("--warn-only", is_flag=True, help="Report findings but always exit 0 (do not fail CI).")
@click.option("--json-out", is_flag=True, help="Emit JSON report instead of text.")
def dbt(
    project_dir: str,
    manifest_path: str | None,
    select: tuple[str, ...],
    policy_path: str | None,
    duckdb_path: str | None,
    warn_only: bool,
    json_out: bool,
) -> None:
    """Verify every model in a dbt project — the CI gate for silent SQL bugs.

    Reads target/manifest.json (run `dbt compile` first). Parse-only by
    default: no warehouse credentials needed.
    """
    import json as _json
    from verisql.dbt_gate import (
        extract_models, find_manifest, load_manifest, render_text, verify_project,
    )

    try:
        path = manifest_path or find_manifest(project_dir)
        manifest_data = load_manifest(path)
    except (FileNotFoundError, ValueError) as e:
        click.echo(f"error: {e}", err=False)
        sys.exit(2)

    connector = None
    if duckdb_path:
        from verisql.connectors.duckdb_conn import DuckDBConnector
        connector = DuckDBConnector.from_path(duckdb_path)

    policy = None
    if policy_path:
        from verisql.policy import Policy
        policy = Policy.from_yaml(policy_path)

    models = extract_models(manifest_data, select=list(select) or None)
    result = verify_project(models, policy=policy, connector=connector)

    if json_out:
        click.echo(_json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(render_text(result))

    if warn_only:
        sys.exit(0)
    sys.exit(2 if result.blocked else (1 if result.review else 0))


if __name__ == "__main__":
    main()
