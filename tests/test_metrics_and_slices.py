from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import forecastops as fops
from forecastops.core.evaluate import evaluate


def _overall(metrics: list, name: str) -> float:
    for metric in metrics:
        if metric.metric_name == name and metric.slice_name is None and metric.benchmark_name is None:
            return metric.metric_value
    raise AssertionError(f"metric {name!r} not found")


def test_smape_and_pinball_values() -> None:
    frame = pd.DataFrame(
        {
            "series_id": ["s", "s"],
            "cutoff_time": pd.to_datetime(["2026-01-01", "2026-01-01"]),
            "target_time": pd.to_datetime(["2026-01-02", "2026-01-03"]),
            "yhat": [11.0, 19.0],
            "actual": [10.0, 20.0],
            "yhat_p10": [8.0, 16.0],
            "yhat_p90": [12.0, 24.0],
        }
    )

    metrics = evaluate(frame, metrics=["smape", "pinball"], run_id="t").metrics

    # sMAPE as a ratio: mean(2*|pred-actual| / (|actual|+|pred|)).
    expected_smape = ((2 * 1 / 21) + (2 * 1 / 39)) / 2
    assert _overall(metrics, "smape") == pytest.approx(expected_smape)
    # Pinball averaged over p10 (loss 0.3) and p90 (loss 0.3).
    assert _overall(metrics, "pinball") == pytest.approx(0.3)


def test_pinball_skipped_without_quantiles() -> None:
    frame = pd.DataFrame(
        {
            "series_id": ["s", "s"],
            "cutoff_time": pd.to_datetime(["2026-01-01", "2026-01-01"]),
            "target_time": pd.to_datetime(["2026-01-02", "2026-01-03"]),
            "yhat": [11.0, 19.0],
            "actual": [10.0, 20.0],
        }
    )

    names = {m.metric_name for m in evaluate(frame, run_id="t").metrics}
    assert "smape" in names
    assert "pinball" not in names  # point forecast: no quantile columns


def test_capture_includes_new_metrics(isolated_store: Path) -> None:
    forecast = pd.DataFrame(
        {
            "target_time": pd.date_range("2026-01-02", periods=4, freq="D"),
            "prediction": [10.0, 11.0, 12.0, 13.0],
        }
    )
    actuals = pd.DataFrame(
        {
            "target_time": pd.date_range("2026-01-02", periods=4, freq="D"),
            "actual": [10.5, 10.5, 12.5, 12.5],
        }
    )

    run = fops.capture(
        forecast,
        project="metrics-test",
        schema=fops.ForecastSchema(target_time="target_time", prediction="prediction"),
        cutoff=pd.Timestamp("2026-01-01"),
        series_id="s",
        actuals=actuals,
        store=isolated_store,
    )

    assert any(metric.metric_name == "smape" for metric in run.metrics)
