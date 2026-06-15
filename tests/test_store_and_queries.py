from __future__ import annotations

import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import forecastops as fops
from forecastops.core.run import ForecastRun, MetricRecord, ValidationEvent
from forecastops.store.duckdb_index import ensure_store
from forecastops.ui.queries import UIQueries

HOLD_LOCK_SCRIPT = """
import sys
import time

import duckdb

conn = duckdb.connect(sys.argv[1])
print("locked", flush=True)
time.sleep(float(sys.argv[2]))
conn.close()
"""


def test_read_only_connect_retries_while_writer_holds_lock(isolated_store: Path) -> None:
    index = ensure_store(isolated_store)
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK_SCRIPT, str(index.path), "1.5"],
        stdout=subprocess.PIPE,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == b"locked"
        start = time.monotonic()
        with index.connect(read_only=True) as conn:
            count = conn.execute("select count(*) from runs").fetchone()[0]
        elapsed = time.monotonic() - start
        assert count == 0
        assert elapsed > 0.3, "read-only connect should have waited for the writer lock"
    finally:
        proc.wait(timeout=10)


def test_init_runs_ddl_once_per_index(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = ensure_store(isolated_store)

    def fail_connect(**_kwargs: object) -> None:
        raise AssertionError("init() should not reconnect after the first call")

    monkeypatch.setattr(index, "connect", fail_connect)
    index.init()


def _insert_run(index, run_id: str, created_at: datetime) -> None:
    run = ForecastRun(
        run_id=run_id,
        project="agg-test",
        model_name="baseline",
        model_version=None,
        adapter_name="dataframe",
        store_path=index.store.root,
        forecast_artifact_uri=f"{run_id}.parquet",
    )
    index.insert_run(run=run, summary={"created_at": created_at})


def test_runs_aggregates_metrics_and_validation_without_inflation(isolated_store: Path) -> None:
    index = ensure_store(isolated_store)
    index.upsert_project("agg-test")
    _insert_run(index, "run-warn", datetime(2026, 1, 3))
    _insert_run(index, "run-fail", datetime(2026, 1, 2))
    _insert_run(index, "run-pass", datetime(2026, 1, 1))

    index.insert_metrics(
        [
            MetricRecord("run-warn:mae", "run-warn", "mae", 1.5, 4),
            MetricRecord("run-warn:wape", "run-warn", "wape", 0.25, 4),
            MetricRecord("run-warn:bias", "run-warn", "bias", -0.1, 4),
            MetricRecord("run-warn:coverage", "run-warn", "coverage", 0.9, 4),
            MetricRecord("run-warn:skill-mae", "run-warn", "skill_mae", 0.2, 4),
            MetricRecord("run-warn:skill-wape", "run-warn", "skill_wape", -0.1, 4),
            # Sliced metric must not leak into the overall columns.
            MetricRecord(
                "run-warn:mae:east", "run-warn", "mae", 99.0, 2, slice_name="region", slice_value="east"
            ),
            # Benchmark-side metric shares the name but must not shadow the model's value.
            MetricRecord("run-warn:mae:bench", "run-warn", "mae", 42.0, 4, benchmark_name="naive"),
        ]
    )
    index.insert_validation_events(
        "run-warn",
        [
            ValidationEvent("WARN", "W1", "first warning"),
            ValidationEvent("WARN", "W2", "second warning"),
            ValidationEvent("INFO", "I1", "informational"),
        ],
    )
    index.insert_validation_events("run-fail", [ValidationEvent("ERROR", "E1", "broken")])

    rows = {row["run_id"]: row for row in UIQueries(isolated_store).runs()}
    assert len(rows) == 3

    warn = rows["run-warn"]
    assert warn["mae"] == 1.5
    assert warn["wape"] == 0.25
    assert warn["bias"] == -0.1
    assert warn["coverage"] == 0.9
    assert warn["skill_vs_benchmark"] == -0.1
    assert warn["validation_status"] == "WARN"

    assert rows["run-fail"]["validation_status"] == "FAIL"
    assert pd.isna(rows["run-fail"]["mae"])
    assert rows["run-pass"]["validation_status"] == "PASS"


def test_forecast_points_series_filter(isolated_store: Path) -> None:
    times = pd.date_range("2026-01-02", periods=5, freq="D")
    frame = pd.concat(
        [
            pd.DataFrame({"series_id": "alpha", "target_time": times, "yhat": np.arange(5.0)}),
            pd.DataFrame({"series_id": "beta", "target_time": times, "yhat": np.arange(5.0) + 10}),
        ],
        ignore_index=True,
    )
    run = fops.capture(
        frame,
        project="points-test",
        cutoff=pd.Timestamp("2026-01-01"),
        store=isolated_store,
    )

    queries = UIQueries(isolated_store)
    everything = queries.forecast_points(run.run_id)
    assert len(everything) == 10

    beta = queries.forecast_points(run.run_id, series_id="beta")
    assert len(beta) == 5
    assert {point["series_id"] for point in beta} == {"beta"}
    assert [point["target_time"] for point in beta] == sorted(p["target_time"] for p in beta)

    limited = queries.forecast_points(run.run_id, series_id="alpha", limit=2)
    assert len(limited) == 2
    assert queries.forecast_points("missing-run") == []


def test_residuals_beyond_10k_points_and_horizon_buckets(isolated_store: Path) -> None:
    times = pd.date_range("2026-01-01 01:00", periods=4000, freq="h")
    frame = pd.concat(
        [
            pd.DataFrame(
                {
                    "series_id": series,
                    "target_time": times,
                    "yhat": np.linspace(1.0, 40.0, 4000) + offset,
                }
            )
            for offset, series in enumerate(("a", "b", "c"))
        ],
        ignore_index=True,
    )
    actuals = frame.rename(columns={"yhat": "actual"}).copy()
    actuals["actual"] = actuals["actual"] - 0.5

    run = fops.capture(
        frame,
        project="residual-test",
        cutoff=pd.Timestamp("2026-01-01"),
        actuals=actuals,
        store=isolated_store,
    )

    queries = UIQueries(isolated_store)
    residuals = queries.residuals(run.run_id, limit=20000)
    assert len(residuals) == 12000, "residuals must cover the full artifact, not a 10k prefix"
    assert all(abs(point["residual"] - 0.5) < 1e-9 for point in residuals)

    # Horizons are 1..4000 hours per series; bucket boundaries are inclusive upper bounds.
    buckets = Counter(point["horizon_bucket"] for point in residuals)
    assert buckets == {
        "0-1h": 3,
        "1-6h": 15,
        "6-24h": 54,
        "24-48h": 72,
        "48h-7d": 360,
        "7d+": 11496,
    }

    short = queries.residuals(run.run_id, horizon_bucket="0-1h", limit=20000)
    assert len(short) == 3
    assert {point["horizon_bucket"] for point in short} == {"0-1h"}

    one_series = queries.residuals(run.run_id, series_id="b", limit=20000)
    assert len(one_series) == 4000

    limited = queries.residuals(run.run_id, limit=10)
    assert len(limited) == 10
