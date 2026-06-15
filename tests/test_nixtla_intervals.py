from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import forecastops as fops
from forecastops.adapters.nixtla import NixtlaAdapter
from forecastops.core.run import CaptureContext, ForecastRun
from forecastops.store.parquet import read_artifact


def _nixtla_frame() -> pd.DataFrame:
    """AutoARIMA point forecast with symmetric 80% and 90% prediction intervals."""
    return pd.DataFrame(
        {
            "unique_id": ["s"] * 3,
            "ds": pd.date_range("2026-01-02", periods=3, freq="D"),
            "AutoARIMA": [10.0, 11.0, 12.0],
            "AutoARIMA-lo-90": [5.0, 6.0, 7.0],
            "AutoARIMA-hi-90": [15.0, 16.0, 17.0],
            "AutoARIMA-lo-80": [7.0, 8.0, 9.0],
            "AutoARIMA-hi-80": [13.0, 14.0, 15.0],
        }
    )


def _actuals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unique_id": ["s"] * 3,
            "ds": pd.date_range("2026-01-02", periods=3, freq="D"),
            "y": [10.5, 11.5, 16.5],
        }
    )


def _metric_names(run: ForecastRun) -> set[str]:
    return {metric.metric_name for metric in run.metrics}


def test_capture_emits_interval_and_pinball_metrics(isolated_store: Path) -> None:
    run = fops.capture(
        _nixtla_frame(),
        adapter="nixtla",
        project="nixtla-intervals",
        cutoff=pd.Timestamp("2026-01-01"),
        actuals=_actuals(),
        store=isolated_store,
    )

    names = _metric_names(run)
    assert "coverage" in names
    assert "interval_width" in names
    assert "pinball" in names

    coverage = next(m for m in run.metrics if m.metric_name == "coverage" and m.slice_name is None)
    width = next(m for m in run.metrics if m.metric_name == "interval_width" and m.slice_name is None)
    assert coverage.metric_value is not None
    assert width.metric_value is not None

    # Point predictions come from AutoARIMA, never an interval column.
    frame = read_artifact(run.forecast_artifact_uri)
    assert frame["yhat"].tolist() == [10.0, 11.0, 12.0]
    assert frame["model_name"].dropna().iloc[0] == "AutoARIMA"


def test_level_to_quantile_mapping(isolated_store: Path) -> None:
    run = fops.capture(
        _nixtla_frame(),
        adapter="nixtla",
        project="nixtla-quantiles",
        cutoff=pd.Timestamp("2026-01-01"),
        actuals=_actuals(),
        store=isolated_store,
    )
    frame = read_artifact(run.forecast_artifact_uri).sort_values("target_time")

    # level 90 -> lower p05 / upper p95; level 80 -> lower p10 / upper p90.
    for column in ["yhat_p05", "yhat_p95", "yhat_p10", "yhat_p90"]:
        assert column in frame.columns, f"missing {column}"

    assert frame["yhat_p05"].tolist() == [5.0, 6.0, 7.0]
    assert frame["yhat_p95"].tolist() == [15.0, 16.0, 17.0]
    assert frame["yhat_p10"].tolist() == [7.0, 8.0, 9.0]
    assert frame["yhat_p90"].tolist() == [13.0, 14.0, 15.0]

    # Widest interval (level 90) drives the bounds.
    assert frame["yhat_lower"].tolist() == [5.0, 6.0, 7.0]
    assert frame["yhat_upper"].tolist() == [15.0, 16.0, 17.0]


def test_explicit_model_col(isolated_store: Path) -> None:
    frame = pd.DataFrame(
        {
            "unique_id": ["s"] * 2,
            "ds": pd.date_range("2026-01-02", periods=2, freq="D"),
            "AutoARIMA": [1.0, 2.0],
            "Naive": [3.0, 4.0],
            "Naive-lo-90": [1.0, 2.0],
            "Naive-hi-90": [5.0, 6.0],
        }
    )
    run = fops.capture(
        frame,
        adapter="nixtla",
        project="nixtla-explicit",
        cutoff=pd.Timestamp("2026-01-01"),
        model_col="Naive",
        store=isolated_store,
    )
    artifact = read_artifact(run.forecast_artifact_uri)
    assert artifact["yhat"].tolist() == [3.0, 4.0]
    assert artifact["model_name"].dropna().iloc[0] == "Naive"
    assert "yhat_p05" in artifact.columns
    assert artifact["yhat_lower"].tolist() == [1.0, 2.0]
    assert artifact["yhat_upper"].tolist() == [5.0, 6.0]


def test_plain_point_forecast_has_no_quantiles(isolated_store: Path) -> None:
    frame = pd.DataFrame(
        {
            "unique_id": ["s"] * 2,
            "ds": pd.date_range("2026-01-02", periods=2, freq="D"),
            "AutoARIMA": [1.0, 2.0],
        }
    )
    run = fops.capture(
        frame,
        adapter="nixtla",
        project="nixtla-plain",
        cutoff=pd.Timestamp("2026-01-01"),
        actuals=pd.DataFrame(
            {
                "unique_id": ["s"] * 2,
                "ds": pd.date_range("2026-01-02", periods=2, freq="D"),
                "y": [1.0, 2.0],
            }
        ),
        store=isolated_store,
    )
    artifact = read_artifact(run.forecast_artifact_uri)
    assert artifact["yhat"].tolist() == [1.0, 2.0]
    quantile_cols = [c for c in artifact.columns if c.startswith("yhat_p")]
    assert quantile_cols == []
    assert "yhat_lower" not in artifact.columns
    assert "pinball" not in _metric_names(run)


def test_unsupported_interval_levels_warn_and_skip_quantiles(isolated_store: Path) -> None:
    frame = pd.DataFrame(
        {
            "unique_id": ["s"] * 2,
            "ds": pd.date_range("2026-01-02", periods=2, freq="D"),
            "AutoARIMA": [10.0, 11.0],
            "AutoARIMA-lo-95": [5.0, 6.0],
            "AutoARIMA-hi-95": [15.0, 16.0],
        }
    )

    with pytest.warns(UserWarning, match="skipped interval level"):
        run = fops.capture(
            frame,
            adapter="nixtla",
            project="nixtla-unsupported-level",
            cutoff=pd.Timestamp("2026-01-01"),
            actuals=_actuals().head(2),
            store=isolated_store,
        )

    artifact = read_artifact(run.forecast_artifact_uri)
    assert "yhat_lower" in artifact.columns
    assert "yhat_upper" in artifact.columns
    assert [column for column in artifact.columns if column.startswith("yhat_p")] == []
    assert "coverage" in _metric_names(run)
    assert "interval_width" in _metric_names(run)
    assert "pinball" not in _metric_names(run)


def test_multiple_models_no_interval_leak(isolated_store: Path) -> None:
    # AutoARIMA is the point model (first non-interval column); Naive's interval columns
    # must not leak into the selected model's bounds or quantiles.
    frame = pd.DataFrame(
        {
            "unique_id": ["s"] * 2,
            "ds": pd.date_range("2026-01-02", periods=2, freq="D"),
            "AutoARIMA": [10.0, 11.0],
            "AutoARIMA-lo-90": [5.0, 6.0],
            "AutoARIMA-hi-90": [15.0, 16.0],
            "Naive": [1.0, 2.0],
            "Naive-lo-90": [0.0, 0.0],
            "Naive-hi-90": [100.0, 100.0],
        }
    )
    context = CaptureContext(
        project="nixtla-multi",
        run_id="nixtla-multi-run",
        cutoff=pd.Timestamp("2026-01-01"),
    )
    normalized = NixtlaAdapter().normalize(frame, context=context).frame.sort_values("target_time")

    assert normalized["yhat"].tolist() == [10.0, 11.0]
    # Bounds come from AutoARIMA, not Naive's wide [0, 100] band.
    assert normalized["yhat_lower"].tolist() == [5.0, 6.0]
    assert normalized["yhat_upper"].tolist() == [15.0, 16.0]
    assert normalized["yhat_p05"].tolist() == [5.0, 6.0]
    assert normalized["yhat_p95"].tolist() == [15.0, 16.0]
