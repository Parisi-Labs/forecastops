from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opentelemetry import metrics as otel_metrics

from forecastops.core.config import load_config
from forecastops.core.run import MetricRecord

METRIC_NAME_MAP = {
    "mae": "forecast.error.mae",
    "rmse": "forecast.error.rmse",
    "wape": "forecast.error.wape",
    "smape": "forecast.error.smape",
    "bias": "forecast.error.bias",
    "coverage": "forecast.probabilistic.coverage",
    "interval_width": "forecast.probabilistic.interval_width",
    "pinball": "forecast.probabilistic.pinball",
}

_INSTRUMENT_SCOPE = "forecastops"
_GAUGES: dict[str, otel_metrics._Gauge] = {}


def _gauge(name: str) -> otel_metrics._Gauge:
    """Return a cached gauge bound to the global OpenTelemetry meter provider.

    Evaluation metrics are point-in-time values per run (and can be negative,
    e.g. bias and skill), so gauges are the right instrument — histograms
    reject negative amounts. Instruments are cached at module level so
    constructing an emitter per call is cheap. Before an SDK meter provider is
    installed the API hands back proxy instruments, which start delegating once
    a real provider is configured.
    """
    gauge = _GAUGES.get(name)
    if gauge is None:
        meter = otel_metrics.get_meter(_INSTRUMENT_SCOPE)
        gauge = meter.create_gauge(name, description=f"ForecastOps aggregate metric {name}")
        _GAUGES[name] = gauge
    return gauge


@dataclass(slots=True)
class ForecastMetricEmitter:
    """Emit aggregate forecast metrics through the global OpenTelemetry API.

    Only aggregate metric values, counts, and identifying attributes are
    emitted — never raw forecast points. Recording goes through
    ``opentelemetry.metrics.get_meter``, so it is a no-op unless an SDK meter
    provider is configured (see
    :func:`forecastops.otel.configure_console_export`). When ``enabled`` is
    left as ``None`` the config-driven switch (``otel.enabled`` in
    forecastops.yaml or ``FOPS_OTEL_ENABLED``) decides whether values are
    recorded; the ``emitted`` list is always populated for local inspection.
    """

    namespace: str = "forecastops"
    emitted: list[tuple[str, float, dict[str, Any]]] = field(default_factory=list)
    enabled: bool | None = None

    def emit(
        self, metrics: list[MetricRecord], *, base_attributes: dict[str, Any] | None = None
    ) -> None:
        enabled = load_config().otel_enabled if self.enabled is None else self.enabled
        for metric in metrics:
            name = metric_name(metric.metric_name)
            attributes = safe_metric_attributes(metric, base_attributes or {})
            self.emitted.append((name, metric.metric_value, attributes))
            if enabled:
                _gauge(name).set(metric.metric_value, attributes=attributes)


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
