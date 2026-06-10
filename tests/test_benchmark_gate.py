"""Wire the benchmark into CI: catch-rate must not regress below the gate."""
import pytest

duckdb = pytest.importorskip("duckdb")


def test_benchmark_meets_gate():
    from benchmarks.run_benchmark import run
    assert run() == 0, "benchmark recall/precision fell below gate thresholds"
