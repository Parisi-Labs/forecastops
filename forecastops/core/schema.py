from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

QUANTILE_COLUMN_PATTERN = re.compile(r"yhat_p(?:0[1-9]|[1-9]\d)")
QUANTILE_LIKE_COLUMN_PATTERN = re.compile(r"yhat_p\d+")


@dataclass(frozen=True, slots=True)
class ForecastSchema:
    """Column mapping for generic dataframe forecasts."""

    series_id: str | None = None
    cutoff_time: str | None = None
    target_time: str | None = None
    prediction: str | None = None
    actual: str | None = None
    actual_available_at: str | None = None
    lower: str | None = None
    upper: str | None = None
    interval_level: str | float | None = None
    benchmark_yhat: str | None = None
    benchmark_name: str | None = None
    benchmark_version: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    forecast_created_at: str | None = None
    data_snapshot_id: str | None = None
    source: str | None = None
    quantiles: dict[float, str] = field(default_factory=dict)
    extra_columns: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ForecastSchema | None:
        if data is None:
            return None
        allowed = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(
                f"Unknown ForecastSchema keys: {', '.join(unknown)}. "
                f"Allowed keys: {', '.join(sorted(allowed))}"
            )
        clean = dict(data)
        quantiles = clean.get("quantiles")
        if isinstance(quantiles, dict):
            clean["quantiles"] = {float(key): value for key, value in quantiles.items()}
        return cls(**clean)


CANONICAL_REQUIRED_COLUMNS = [
    "run_id",
    "series_id",
    "cutoff_time",
    "target_time",
    "horizon",
    "yhat",
    "model_name",
]

CANONICAL_OPTIONAL_COLUMNS = [
    "horizon_duration",
    "model_version",
    "yhat_lower",
    "yhat_upper",
    "interval_level",
    "forecast_created_at",
    "data_snapshot_id",
    "source",
    "actual",
    "actual_available_at",
    "benchmark_yhat",
    "benchmark_name",
    "benchmark_version",
]


def quantile_column_name(quantile: float) -> str:
    scaled = round(quantile * 100)
    if scaled <= 0 or scaled >= 100:
        raise ValueError(f"Quantile must be between 0 and 1, got {quantile!r}")
    return f"yhat_p{scaled:02d}"
