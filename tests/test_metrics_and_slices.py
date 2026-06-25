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


def test_pinball_ignores_noncanonical_quantile_columns() -> None:
    frame = pd.DataFrame(
        {
            "series_id": ["s", "s"],
            "cutoff_time": pd.to_datetime(["2026-01-01", "2026-01-01"]),
            "target_time": pd.to_datetime(["2026-01-02", "2026-01-03"]),
            "yhat": [11.0, 19.0],
            "actual": [10.0, 20.0],
            "yhat_p05": [8.0, 16.0],
            "yhat_p10": [8.0, 16.0],
            "yhat_p90": [12.0, 24.0],
            "yhat_p5": [100.0, 100.0],
        }
    )
    canonical = frame.drop(columns=["yhat_p5"])

    with_extra = evaluate(frame, metrics=["pinball"], run_id="t").metrics
    without_extra = evaluate(canonical, metrics=["pinball"], run_id="t").metrics

    assert _overall(with_extra, "pinball") == pytest.approx(_overall(without_extra, "pinball"))


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


def test_capture_emits_coverage_gap_when_interval_level_is_available(isolated_store: Path) -> None:
    forecast = pd.DataFrame(
        {
            "target_time": pd.date_range("2026-01-02", periods=4, freq="D"),
            "prediction": [10.0, 11.0, 12.0, 13.0],
            "lower": [9.0, 10.0, 11.0, 12.0],
            "upper": [11.0, 12.0, 13.0, 14.0],
            "level": [90, 90, 90, 90],
        }
    )
    actuals = pd.DataFrame(
        {
            "target_time": pd.date_range("2026-01-02", periods=4, freq="D"),
            "actual": [10.0, 11.0, 12.0, 15.0],
        }
    )

    run = fops.capture(
        forecast,
        project="coverage-gap-test",
        schema=fops.ForecastSchema(
            target_time="target_time",
            prediction="prediction",
            lower="lower",
            upper="upper",
            interval_level="level",
        ),
        cutoff=pd.Timestamp("2026-01-01"),
        series_id="s",
        actuals=actuals,
        store=isolated_store,
    )
    metrics = {
        metric.metric_name: metric.metric_value
        for metric in run.metrics
        if metric.slice_name is None and metric.benchmark_name is None
    }

    assert metrics["coverage"] == 0.75
    assert metrics["coverage_gap"] == pytest.approx(-0.15)


def test_capture_slices_metrics_by_extra_column(isolated_store: Path) -> None:
    times = pd.date_range("2026-01-02", periods=4, freq="D")
    forecast = pd.DataFrame(
        {
            "series_id": ["east"] * 4 + ["west"] * 4,
            "target_time": list(times) * 2,
            "prediction": [10.0, 11.0, 12.0, 13.0, 20.0, 21.0, 22.0, 23.0],
            "region": ["east"] * 4 + ["west"] * 4,
        }
    )
    actuals = pd.DataFrame(
        {
            "series_id": ["east"] * 4 + ["west"] * 4,
            "target_time": list(times) * 2,
            "actual": [10.5, 10.5, 12.5, 12.5, 19.0, 22.0, 21.0, 24.0],
        }
    )

    run = fops.capture(
        forecast,
        project="slice-test",
        schema=fops.ForecastSchema(
            series_id="series_id",
            target_time="target_time",
            prediction="prediction",
            extra_columns=["region"],
        ),
        cutoff=pd.Timestamp("2026-01-01"),
        actuals=actuals,
        store=isolated_store,
    )

    region_slices = {
        metric.slice_value
        for metric in run.metrics
        if metric.slice_name == "region" and metric.metric_name == "mae"
    }
    assert region_slices == {"east", "west"}
