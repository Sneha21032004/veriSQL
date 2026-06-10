from typing import Any

from verisql.connectors.base import ColumnStats, ensure_limited, guard_mutation

try:
    from google.cloud import bigquery
except ImportError as e:  # pragma: no cover
    raise ImportError("Install with `pip install verisql[bigquery]`") from e


class BigQueryConnector:
    """BigQuery adapter. Uses dry-run for the EXPLAIN-equivalent: a dry-run validates
    the query and reports bytes that *would* be scanned without running it — the ideal
    cheap signal for a verifier. Live reads are capped with maximum_bytes_billed.
    """

    dialect = "bigquery"

    def __init__(self, client: Any, dataset: str, max_bytes_billed: int = 1_000_000_000):
        self._client = client
        self._dataset = dataset
        self._max_bytes = max_bytes_billed

    @classmethod
    def connect(cls, dataset: str, project: str | None = None, **kwargs: Any) -> "BigQueryConnector":
        return cls(bigquery.Client(project=project, **kwargs), dataset=dataset)

    def list_tables(self) -> list[str]:
        rows = self._client.query(
            f"SELECT table_name FROM `{self._dataset}.INFORMATION_SCHEMA.TABLES`"
        ).result()
        return [r[0] for r in rows]

    def list_columns(self, table: str) -> list[str]:
        rows = self._client.query(
            f"SELECT column_name FROM `{self._dataset}.INFORMATION_SCHEMA.COLUMNS` "
            f"WHERE table_name = @t",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("t", "STRING", table)]
            ),
        ).result()
        return [r[0] for r in rows]

    def execute_readonly(self, sql: str, max_rows: int = 100) -> list[tuple[Any, ...]]:
        guard_mutation(sql, self.dialect)
        sql = ensure_limited(sql, max_rows)
        cfg = bigquery.QueryJobConfig(maximum_bytes_billed=self._max_bytes)
        rows = self._client.query(sql, job_config=cfg).result()
        return [tuple(r.values()) for r in rows]

    def explain(self, sql: str) -> str:
        """Dry-run: validate + estimate scanned bytes without executing."""
        guard_mutation(sql, self.dialect)
        cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        job = self._client.query(sql, job_config=cfg)
        gib = job.total_bytes_processed / (1024 ** 3) if job.total_bytes_processed else 0.0
        # render rows≈ estimate so ExplainPlanCheck's rows-parser can read it
        est_rows = int(job.total_bytes_processed / 100) if job.total_bytes_processed else 0
        return f"BigQuery dry-run: scans {gib:.3f} GiB (rows={est_rows})"

    def column_stats(self, table: str, column: str) -> ColumnStats | None:
        try:
            rows = self._client.query(
                f"SELECT MIN(`{column}`), MAX(`{column}`), APPROX_COUNT_DISTINCT(`{column}`) "
                f"FROM `{self._dataset}.{table}`"
            ).result()
        except Exception:
            return None
        for r in rows:
            return ColumnStats(min=r[0], max=r[1], approx_distinct=r[2])
        return None
