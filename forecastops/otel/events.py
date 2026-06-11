from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FORECAST_VALIDATION_FAILED = "forecast.validation.failed"
FORECAST_VALIDATION_WARNING = "forecast.validation.warning"
FORECAST_LEAKAGE_DETECTED = "forecast.leakage.detected"
FORECAST_ACTUALS_MISSING = "forecast.actuals.missing"
FORECAST_BENCHMARK_MISSING = "forecast.benchmark.missing"
FORECAST_COVERAGE_BELOW_THRESHOLD = "forecast.coverage.below_threshold"
FORECAST_REPORT_GENERATED = "forecast.report.generated"
FORECAST_ARTIFACT_WRITTEN = "forecast.artifact.written"


@dataclass(frozen=True, slots=True)
class ForecastEvent:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)


def validation_event_name(severity: str) -> str:
    if severity == "ERROR":
        return FORECAST_VALIDATION_FAILED
    if severity == "WARN":
        return FORECAST_VALIDATION_WARNING
    return "forecast.validation.info"

