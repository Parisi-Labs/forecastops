from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest
from opentelemetry import metrics as otel_metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

import forecastops as fops
from forecastops.core.config import load_config
from forecastops.core.run import MetricRecord, utc_now
from forecastops.otel.metrics import ForecastMetricEmitter
from forecastops.otel.trace import ForecastTrace

SAFE_ATTRIBUTE_KEYS = {
    "forecast.project.name",
    "forecast.environment",
    "forecast.model.name",
    "forecast.model.version",
    "forecast.run.kind",
    "forecast.adapter.name",
    "forecast.metric.name",
    "forecast.horizon.bucket",
    "forecast.benchmark.name",
    "forecast.slice.name",
    "forecast.slice.value",
}


@pytest.fixture(scope="module")
def metric_reader() -> InMemoryMetricReader:
    # The global OpenTelemetry meter provider can only be set once per process,
    # so a single in-memory reader is shared by every test in this module.
    reader = InMemoryMetricReader()
    otel_metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))
    return reader


def _record(metric_name: str, value: float) -> MetricRecord:
    return MetricRecord(
        metric_id=f"m-{metric_name}",
        run_id="run-otel",
        metric_name=metric_name,
        metric_value=value,
        points_count=4,
        horizon_bucket="6-24h",
        created_at=utc_now(),
    )


def _collect_points(reader: InMemoryMetricReader) -> dict[str, list[Any]]:
    points: dict[str, list[Any]] = {}
    data = reader.get_metrics_data()
    for resource_metrics in getattr(data, "resource_metrics", []) or []:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                for point in metric.data.data_points:
                    points.setdefault(metric.name, []).append(point)
    return points


def _points_for_project(points: dict[str, list[Any]], name: str, project: str) -> list[Any]:
    return [
        point
        for point in points.get(name, [])
        if dict(point.attributes).get("forecast.project.name") == project
    ]


def test_emit_records_through_global_meter_provider(
    metric_reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FOPS_OTEL_ENABLED", "true")
    emitter = ForecastMetricEmitter()
    emitter.emit(
        [_record("mae", 1.5)],
        base_attributes={"forecast.project.name": "otel-direct", "target_time": "unsafe"},
    )

    assert emitter.emitted == [
        (
            "forecast.error.mae",
            1.5,
            {
                "forecast.project.name": "otel-direct",
                "forecast.metric.name": "mae",
                "forecast.horizon.bucket": "6-24h",
            },
        )
    ]
    matches = _points_for_project(
        _collect_points(metric_reader), "forecast.error.mae", "otel-direct"
    )
    assert len(matches) == 1
    assert matches[0].value == 1.5
    assert set(dict(matches[0].attributes)) <= SAFE_ATTRIBUTE_KEYS


def test_emit_is_noop_when_disabled(
    metric_reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FOPS_OTEL_ENABLED", raising=False)
    emitter = ForecastMetricEmitter()
    emitter.emit([_record("rmse", 2.0)], base_attributes={"forecast.project.name": "otel-off"})

    assert emitter.emitted  # local inspection list is still populated
    assert not _points_for_project(_collect_points(metric_reader), "forecast.error.rmse", "otel-off")


def test_capture_exports_aggregate_metrics_only(
    metric_reader: InMemoryMetricReader,
    isolated_store: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOPS_OTEL_ENABLED", "1")
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
        project="otel-capture",
        schema=fops.ForecastSchema(target_time="target_time", prediction="prediction"),
        cutoff=pd.Timestamp("2026-01-01"),
        series_id="series-a",
        actuals=actuals,
        model_name="baseline",
        store=isolated_store,
    )

    assert any(metric.metric_name == "mae" for metric in run.metrics)
    points = _collect_points(metric_reader)
    matches = _points_for_project(points, "forecast.error.mae", "otel-capture")
    assert len(matches) >= 1
    expected_mae = next(m.metric_value for m in run.metrics if m.metric_name == "mae")
    assert any(point.value == pytest.approx(expected_mae) for point in matches)
    # Privacy invariant: only aggregate values and safe identifying attributes,
    # never raw forecast points or timestamps.
    for point_list in points.values():
        for point in point_list:
            assert set(dict(point.attributes)) <= SAFE_ATTRIBUTE_KEYS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("off", False),
        (None, False),
    ],
)
def test_trace_and_metric_switches_agree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None, expected: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    if value is None:
        monkeypatch.delenv("FOPS_OTEL_ENABLED", raising=False)
    else:
        monkeypatch.setenv("FOPS_OTEL_ENABLED", value)

    metrics_enabled = load_config().otel_enabled
    trace = ForecastTrace(index=cast(Any, None), run_id="run-switch")
    assert metrics_enabled is expected
    assert trace.enabled is expected


def test_switches_honor_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FOPS_OTEL_ENABLED", raising=False)
    (tmp_path / "forecastops.yaml").write_text("otel:\n  enabled: true\n", encoding="utf-8")

    trace = ForecastTrace(index=cast(Any, None), run_id="run-config")
    assert load_config().otel_enabled is True
    assert trace.enabled is True
