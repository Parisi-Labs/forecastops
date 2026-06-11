"""OpenTelemetry-compatible semantic constants and optional helpers."""

from forecastops.otel.exporters import configure_console_export
from forecastops.otel.metrics import ForecastMetricEmitter

__all__ = ["ForecastMetricEmitter", "configure_console_export"]
