from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import forecastops as fops
from forecastops.adapters.registry import resolve_adapter
from forecastops.core.run import CaptureContext, MetricRecord, utc_now
from forecastops.otel.metrics import ForecastMetricEmitter, metric_name


def test_forecast_decorator_returns_run(isolated_store: Path) -> None:
    @fops.forecast(
        project="decorator-test",
        series_id="s",
        cutoff=lambda ctx: pd.Timestamp("2026-01-01"),
        store=isolated_store,
    )
    def make_forecast() -> pd.DataFrame:
        return pd.DataFrame({"ds": pd.date_range("2026-01-02", periods=2), "yhat": [1.0, 2.0]})

    run = make_forecast()

    assert run.run_id
    assert run.adapter_name == "prophet"


def test_model_wrapper_preserves_predict_return(isolated_store: Path) -> None:
    class Model:
        def fit(self, frame):
            self.history = frame
            return self

        def predict(self, future):
            return pd.DataFrame({"ds": future["ds"], "yhat": [5.0] * len(future)})

    model = fops.wrap(
        Model(),
        project="wrapper-test",
        series_id="s",
        cutoff=lambda self: self.history["ds"].max(),
        store=isolated_store,
    )
    model.fit(pd.DataFrame({"ds": pd.date_range("2026-01-01", periods=3), "y": [1, 2, 3]}))
    output = model.predict(pd.DataFrame({"ds": pd.date_range("2026-01-04", periods=2)}))

    assert isinstance(output, pd.DataFrame)
    assert model.fops_last_run.run_id


def test_darts_like_adapter() -> None:
    class TimeSeries:
        def __init__(self) -> None:
            self.time_index = pd.date_range("2026-01-02", periods=2)
            self.components = ["component-a"]

        def values(self):
            return np.array([1.0, 2.0])

    context = CaptureContext(
        project="darts",
        run_id="darts-run",
        cutoff=pd.Timestamp("2026-01-01"),
    )
    adapter = resolve_adapter(TimeSeries(), "darts", context)
    frame = adapter.normalize(TimeSeries(), context=context).frame

    assert frame["series_id"].astype(str).tolist() == ["component-a", "component-a"]
    assert frame["yhat"].tolist() == [1.0, 2.0]


def test_gluonts_like_adapter() -> None:
    class Forecast:
        start_date = pd.Timestamp("2026-01-02")
        prediction_length = 2
        freq = "D"
        item_id = "item-a"

        def quantile(self, q):
            return np.array([q, q + 1])

    context = CaptureContext(
        project="gluonts",
        run_id="gluonts-run",
        cutoff=pd.Timestamp("2026-01-01"),
    )
    adapter = resolve_adapter(Forecast(), "gluonts", context)
    frame = adapter.normalize(Forecast(), context=context).frame

    assert "yhat_p10" in frame
    assert frame["yhat"].tolist() == [0.5, 1.5]


def test_metric_emitter_uses_safe_names() -> None:
    record = MetricRecord(
        metric_id="m",
        run_id="r",
        metric_name="skill_mae",
        metric_value=0.2,
        points_count=10,
        benchmark_name="prod",
        horizon_bucket="6-24h",
        created_at=utc_now(),
    )
    emitter = ForecastMetricEmitter()
    emitter.emit([record], base_attributes={"forecast.project.name": "demo", "target_time": "unsafe"})

    assert metric_name("skill_mae") == "forecast.benchmark.skill"
    assert emitter.emitted[0][2] == {
        "forecast.project.name": "demo",
        "forecast.metric.name": "skill_mae",
        "forecast.horizon.bucket": "6-24h",
        "forecast.benchmark.name": "prod",
    }
