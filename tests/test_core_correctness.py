from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import forecastops as fops
from forecastops.core.compare import compare
from forecastops.core.diff import diff
from forecastops.core.evaluate import attach_actuals, evaluate
from forecastops.core.run import ForecastRun
from forecastops.core.schema import ForecastSchema
from forecastops.core.validate import validate_forecast
from forecastops.store.parquet import read_artifact


def _forecast_frame(tz: str | None = None) -> pd.DataFrame:
    cutoff = pd.Timestamp("2026-01-01", tz=tz)
    return pd.DataFrame(
        {
            "run_id": ["r"] * 3,
            "series_id": ["s"] * 3,
            "cutoff_time": [cutoff] * 3,
            "target_time": pd.date_range("2026-01-02", periods=3, freq="D", tz=tz),
            "horizon": [1, 2, 3],
            "yhat": [11.0, 21.0, 29.0],
            "model_name": ["model"] * 3,
        }
    )


def _actuals(tz: str | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "target_time": pd.date_range("2026-01-02", periods=3, freq="D", tz=tz),
            "actual": [10.0, 20.0, 30.0],
        }
    )


def _overall_metrics(metrics: list) -> dict[str, float]:
    return {
        metric.metric_name: metric.metric_value for metric in metrics if metric.slice_name is None
    }


def test_tz_aware_actuals_join_naive_forecast() -> None:
    result = evaluate(_forecast_frame(tz=None), actuals=_actuals(tz="UTC"), run_id="r", slices=[])
    metrics = _overall_metrics(result.metrics)
    assert metrics["mae"] == 1.0
    assert metrics["count"] == 3.0


def test_tz_naive_actuals_join_aware_forecast() -> None:
    result = evaluate(_forecast_frame(tz="UTC"), actuals=_actuals(tz=None), run_id="r", slices=[])
    metrics = _overall_metrics(result.metrics)
    assert metrics["mae"] == 1.0


def test_duplicate_actuals_raise_clear_error() -> None:
    duplicated = pd.concat([_actuals(), _actuals().head(1)], ignore_index=True)
    with pytest.raises(ValueError, match=r"actuals.*duplicate"):
        evaluate(_forecast_frame(), actuals=duplicated, run_id="r")


def test_duplicate_benchmark_raises_clear_error() -> None:
    frame = _forecast_frame()
    frame["actual"] = [10.0, 20.0, 30.0]
    benchmark = pd.DataFrame(
        {
            "target_time": list(frame["target_time"]) * 2,
            "benchmark_yhat": [13.0, 24.0, 25.0] * 2,
        }
    )
    with pytest.raises(ValueError, match=r"benchmark.*duplicate"):
        compare(frame, benchmark=benchmark)


def test_unmatched_actuals_warn_instead_of_silently_empty() -> None:
    stale = _actuals()
    stale["target_time"] = stale["target_time"] - pd.Timedelta(days=365)
    with pytest.warns(UserWarning, match="zero forecast rows"):
        result = evaluate(_forecast_frame(), actuals=stale, run_id="r", slices=[])
    assert "mae" not in _overall_metrics(result.metrics)


def test_diff_aligns_timezones_and_tolerates_missing_run_id() -> None:
    base = _forecast_frame(tz=None).drop(columns=["run_id"])
    candidate = _forecast_frame(tz="UTC").drop(columns=["run_id"])
    candidate["yhat"] = candidate["yhat"] + 1.0

    result = diff(base, candidate)

    assert result.base_run_id == "adhoc"
    assert len(result.forecast_deltas) == 3
    assert result.forecast_deltas["forecast_delta"].tolist() == [1.0, 1.0, 1.0]


def test_benchmarked_capture_keeps_count_and_metric_parity(isolated_store: Path) -> None:
    cutoff = pd.Timestamp("2026-01-01")
    forecast = pd.DataFrame(
        {"ds": pd.date_range("2026-01-02", periods=3, freq="D"), "yhat": [11.0, 21.0, 29.0]}
    )
    actuals = _actuals()
    benchmark = pd.DataFrame(
        {"target_time": actuals["target_time"], "benchmark_yhat": [13.0, 24.0, 25.0]}
    )

    plain = fops.capture(
        forecast,
        project="parity-test",
        series_id="s",
        cutoff=cutoff,
        actuals=actuals,
        store=isolated_store,
    )
    benchmarked = fops.capture(
        forecast,
        project="parity-test",
        series_id="s",
        cutoff=cutoff,
        actuals=actuals,
        benchmark=benchmark,
        store=isolated_store,
    )

    plain_names = {metric.metric_name for metric in plain.metrics}
    model_side_names = {
        metric.metric_name for metric in benchmarked.metrics if metric.benchmark_name is None
    }
    assert "count" in model_side_names
    assert model_side_names == plain_names
    assert any(metric.metric_name == "skill_mae" for metric in benchmarked.metrics)


def test_yhat_pred_column_passes_through_capture(isolated_store: Path) -> None:
    forecast = pd.DataFrame(
        {
            "ds": pd.date_range("2026-01-02", periods=2, freq="D"),
            "yhat": [1.0, 2.0],
            "yhat_pred": ["not", "numeric"],
        }
    )
    run = fops.capture(
        forecast,
        project="quantile-test",
        series_id="s",
        cutoff=pd.Timestamp("2026-01-01"),
        store=isolated_store,
    )
    assert run.run_id


def test_validate_ignores_non_quantile_yhat_p_columns() -> None:
    frame = _forecast_frame().assign(
        yhat_pred=["x", "y", "z"],
        yhat_percentile=["a", "b", "c"],
        yhat_p10=[1.0, 2.0, 3.0],
        yhat_p90=[2.0, 3.0, 4.0],
    )
    events = validate_forecast(frame)
    assert not any(event.code == "quantiles_not_monotonic" for event in events)


def test_schema_from_dict_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="predicton"):
        ForecastSchema.from_dict({"predicton": "yhat"})


def test_schema_from_dict_accepts_known_keys() -> None:
    schema = ForecastSchema.from_dict({"prediction": "yhat", "quantiles": {"0.1": "p10"}})
    assert schema is not None
    assert schema.prediction == "yhat"
    assert schema.quantiles == {0.1: "p10"}
    assert ForecastSchema.from_dict(None) is None


def test_evaluate_without_run_id_uses_adhoc() -> None:
    frame = _forecast_frame().drop(columns=["run_id"])
    frame["actual"] = [10.0, 20.0, 30.0]
    result = evaluate(frame, slices=[])
    assert result.metrics
    assert all(metric.run_id == "adhoc" for metric in result.metrics)


def test_compare_accepts_run_id_keyword() -> None:
    frame = _forecast_frame().drop(columns=["run_id"])
    frame["actual"] = [10.0, 20.0, 30.0]
    benchmark = pd.DataFrame(
        {"target_time": frame["target_time"], "benchmark_yhat": [13.0, 24.0, 25.0]}
    )
    result = compare(frame, benchmark=benchmark, run_id="custom", slices=[])
    assert result.metrics
    assert all(metric.run_id == "custom" for metric in result.metrics)
    assert "count" in _overall_metrics(result.metrics)


def test_forecast_decorator_returns_original_output(isolated_store: Path) -> None:
    @fops.forecast(
        project="decorator-passthrough",
        series_id="s",
        cutoff=pd.Timestamp("2026-01-01"),
        store=isolated_store,
    )
    def make_forecast() -> pd.DataFrame:
        return pd.DataFrame({"ds": pd.date_range("2026-01-02", periods=2), "yhat": [1.0, 2.0]})

    result = make_forecast()

    assert type(result) is pd.DataFrame
    assert result["yhat"].tolist() == [1.0, 2.0]
    assert len(result) == 2


def test_forecast_decorator_return_run_opt_in(isolated_store: Path) -> None:
    @fops.forecast(
        return_run=True,
        project="decorator-run",
        series_id="s",
        cutoff=pd.Timestamp("2026-01-01"),
        store=isolated_store,
    )
    def make_forecast() -> pd.DataFrame:
        return pd.DataFrame({"ds": pd.date_range("2026-01-02", periods=2), "yhat": [1.0, 2.0]})

    run = make_forecast()

    assert isinstance(run, ForecastRun)
    assert isinstance(run.raw_output, pd.DataFrame)


def test_actuals_artifact_uses_resolved_series_id(isolated_store: Path) -> None:
    run = fops.capture(
        pd.DataFrame(
            {"ds": pd.date_range("2026-01-02", periods=3, freq="D"), "yhat": [11.0, 21.0, 29.0]}
        ),
        project="artifact-test",
        series_id="series-a",
        cutoff=pd.Timestamp("2026-01-01"),
        actuals=_actuals(),
        store=isolated_store,
    )

    assert run.actuals_artifact_uri is not None
    actuals_frame = read_artifact(run.actuals_artifact_uri)
    assert set(actuals_frame["series_id"].astype(str)) == {"series-a"}

    forecast_frame = read_artifact(run.forecast_artifact_uri)
    rejoined = attach_actuals(forecast_frame.drop(columns=["actual"]), actuals_frame)
    assert rejoined["actual"].notna().all()
