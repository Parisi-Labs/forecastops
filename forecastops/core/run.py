from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_run_id(project: str, model_name: str | None = None) -> str:
    import secrets

    safe_project = "".join(ch if ch.isalnum() else "-" for ch in project.lower()).strip("-")
    safe_model = "".join(ch if ch.isalnum() else "-" for ch in (model_name or "forecast").lower())
    suffix = secrets.token_hex(6)
    stamp = utc_now().strftime("%Y%m%d%H%M%S")
    return f"{safe_project or 'default'}-{safe_model or 'forecast'}-{stamp}-{suffix}"


@dataclass(slots=True)
class CaptureContext:
    project: str
    run_id: str | None = None
    series_id: Any | None = None
    cutoff: Any | None = None
    target_time: Any | None = None
    model_name: str | None = None
    model_version: str | None = None
    schema: Any | None = None
    adapter_options: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    run_name: str | None = None
    run_kind: str = "forecast"
    store_path: Path | None = None
    allow_insample: bool = False


@dataclass(frozen=True, slots=True)
class DetectionResult:
    matched: bool
    confidence: float
    reason: str
    required_context: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NormalizedForecast:
    frame: pd.DataFrame
    adapter_name: str
    schema_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationEvent:
    severity: str
    code: str
    message: str
    affected_column: str | None = None
    affected_count: int | None = None
    sample: dict[str, Any] | None = None
    event_id: str | None = None

    @property
    def is_error(self) -> bool:
        return self.severity.upper() == "ERROR"


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    run_id: str
    artifact_type: str
    uri: str
    content_type: str
    row_count: int
    byte_size: int
    schema: dict[str, Any]
    sha256: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MetricRecord:
    metric_id: str
    run_id: str
    metric_name: str
    metric_value: float
    points_count: int
    benchmark_name: str | None = None
    horizon_bucket: str | None = None
    slice_name: str | None = None
    slice_value: str | None = None
    series_group: str | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class ForecastRun:
    run_id: str
    project: str
    model_name: str
    model_version: str | None
    adapter_name: str
    store_path: Path
    forecast_artifact_uri: str
    actuals_artifact_uri: str | None = None
    benchmark_artifact_uri: str | None = None
    report_uri: str | None = None
    trace_id: str | None = None
    validation_events: list[ValidationEvent] = field(default_factory=list)
    metrics: list[MetricRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_output: Any | None = None

    @property
    def status(self) -> str:
        if any(event.severity == "ERROR" for event in self.validation_events):
            return "error"
        if any(event.severity == "WARN" for event in self.validation_events):
            return "warning"
        return "ok"

