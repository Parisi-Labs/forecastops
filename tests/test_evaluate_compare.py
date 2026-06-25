from __future__ import annotations

import pandas as pd

from forecastops.core.compare import compare
from forecastops.core.evaluate import evaluate


def _forecast_frame() -> pd.DataFrame:
    cutoff = pd.Timestamp("2026-01-01")
    return pd.DataFrame(
        {
            "run_id": ["r"] * 3,
            "series_id": ["s"] * 3,
            "cutoff_time": [cutoff] * 3,
            "target_time": pd.date_range("2026-01-02", periods=3, freq="D"),
            "horizon": [1, 2, 3],
            "yhat": [11.0, 21.0, 29.0],
            "actual": [10.0, 20.0, 30.0],
            "yhat_lower": [8.0, 18.0, 25.0],
            "yhat_upper": [12.0, 24.0, 31.0],
            "interval_level": [0.9, 0.9, 0.9],
            "model_name": ["model"] * 3,
        }
    )


def test_point_and_interval_metrics() -> None:
    result = evaluate(_forecast_frame(), run_id="r", slices=[])
    metrics = {
        metric.metric_name: metric.metric_value
        for metric in result.metrics
        if metric.slice_name is None
    }

    assert metrics["mae"] == 1.0
    assert round(metrics["rmse"], 6) == 1.0
    assert round(metrics["wape"], 6) == round(3 / 60, 6)
    assert round(metrics["bias"], 6) == round(1 / 3, 6)
    assert metrics["coverage"] == 1.0
    assert round(metrics["coverage_gap"], 6) == 0.1
    assert metrics["interval_width"] == 16 / 3


def test_coverage_gap_distinguishes_nominal_interval_levels() -> None:
    frame = _forecast_frame()

    metrics_50 = {
        metric.metric_name: metric.metric_value
        for metric in evaluate(frame.assign(interval_level=0.5), run_id="r50", slices=[]).metrics
        if metric.slice_name is None
    }
    metrics_90 = {
        metric.metric_name: metric.metric_value
        for metric in evaluate(frame.assign(interval_level=90), run_id="r90", slices=[]).metrics
        if metric.slice_name is None
    }

    assert metrics_50["coverage"] == metrics_90["coverage"] == 1.0
    assert metrics_50["coverage_gap"] == 0.5
    assert round(metrics_90["coverage_gap"], 6) == 0.1


def test_benchmark_skill() -> None:
    frame = _forecast_frame()
    benchmark = frame[["series_id", "target_time"]].copy()
    benchmark["benchmark_yhat"] = [13.0, 24.0, 25.0]

    result = compare(frame, benchmark=benchmark, benchmark_name="incumbent", slices=[])
    metrics = {
        metric.metric_name: metric.metric_value
        for metric in result.metrics
        if metric.slice_name is None
    }

    assert "skill_mae" in metrics
    assert metrics["skill_mae"] > 0
