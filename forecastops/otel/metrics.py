from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from forecastops.core.run import MetricRecord

METRIC_NAME_MAP = {
    "mae": "forecast.error.mae",
    "rmse": "forecast.error.rmse",
    "wape": "forecast.error.wape",
    "bias": "forecast.error.bias",
    "coverage": "forecast.probabilistic.coverage",
    "interval_width": "forecast.probabilistic.interval_width",
}


@dataclass(slots=True)
class ForecastMetricEmitter:
    namespace: str = "forecastops"
    emitted: list[tuple[str, float, dict[str, Any]]] = field(default_factory=list)

    def emit(self, metrics: list[MetricRecord], *, base_attributes: dict[str, Any] | None = None) -> None:
        for metric in metrics:
            name = metric_name(metric.metric_name)
            attributes = safe_metric_attributes(metric, base_attributes or {})
            self.emitted.append((name, metric.metric_value, attributes))


def metric_name(name: str) -> str:
    if name.startswith("skill_"):
        return "forecast.benchmark.skill"
    return METRIC_NAME_MAP.get(name, f"forecast.metric.{name}")


def safe_metric_attributes(metric: MetricRecord, base: dict[str, Any]) -> dict[str, Any]:
    attributes = {
        key: value
        for key, value in base.items()
        if key
        in {
            "forecast.project.name",
            "forecast.environment",
            "forecast.model.name",
            "forecast.model.version",
            "forecast.run.kind",
            "forecast.adapter.name",
        }
        and value is not None
    }
    attributes["forecast.metric.name"] = metric.metric_name
    if metric.horizon_bucket:
        attributes["forecast.horizon.bucket"] = metric.horizon_bucket
    if metric.benchmark_name:
        attributes["forecast.benchmark.name"] = metric.benchmark_name
    if metric.slice_name and metric.slice_value:
        attributes["forecast.slice.name"] = metric.slice_name
        attributes["forecast.slice.value"] = metric.slice_value
    return attributes
