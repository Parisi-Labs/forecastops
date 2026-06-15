from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from forecastops.core.run import ValidationEvent
from forecastops.core.schema import (
    CANONICAL_REQUIRED_COLUMNS,
    QUANTILE_COLUMN_PATTERN,
    QUANTILE_LIKE_COLUMN_PATTERN,
)


def validate_forecast(
    frame: pd.DataFrame,
    *,
    allow_insample: bool = False,
    max_slice_cardinality: int = 100,
) -> list[ValidationEvent]:
    events: list[ValidationEvent] = []
    events.extend(_required_columns(frame))
    if events and any(event.is_error for event in events):
        return events

    events.extend(_required_values(frame))
    events.extend(_timestamp_checks(frame, allow_insample=allow_insample))
    events.extend(_duplicate_checks(frame))
    events.extend(_finite_checks(frame))
    events.extend(_interval_checks(frame))
    events.extend(_quantile_checks(frame))
    events.extend(_actuals_checks(frame))
    events.extend(_cardinality_checks(frame, max_slice_cardinality=max_slice_cardinality))
    if not events:
        events.append(ValidationEvent("INFO", "validation_passed", "Forecast artifact passed validation"))
    return events


def validation_status(events: list[ValidationEvent]) -> str:
    if any(event.severity == "ERROR" for event in events):
        return "FAIL"
    if any(event.severity == "WARN" for event in events):
        return "WARN"
    return "PASS"


def _required_columns(frame: pd.DataFrame) -> list[ValidationEvent]:
    missing = [column for column in CANONICAL_REQUIRED_COLUMNS if column not in frame.columns]
    if not missing:
        return []
    return [
        ValidationEvent(
            "ERROR",
            "missing_required_columns",
            f"Missing required canonical columns: {', '.join(missing)}",
            affected_count=len(missing),
        )
    ]


def _required_values(frame: pd.DataFrame) -> list[ValidationEvent]:
    events: list[ValidationEvent] = []
    for column in CANONICAL_REQUIRED_COLUMNS:
        missing = int(frame[column].isna().sum())
        if missing:
            events.append(
                ValidationEvent(
                    "ERROR",
                    "missing_required_values",
                    f"{column} contains {missing} missing values",
                    affected_column=column,
                    affected_count=missing,
                    sample=_sample_rows(frame[frame[column].isna()]),
                )
            )
    return events


def _timestamp_checks(frame: pd.DataFrame, *, allow_insample: bool) -> list[ValidationEvent]:
    events: list[ValidationEvent] = []
    cutoff = pd.to_datetime(frame["cutoff_time"], errors="coerce")
    target = pd.to_datetime(frame["target_time"], errors="coerce")
    invalid_cutoff = int(cutoff.isna().sum())
    invalid_target = int(target.isna().sum())
    if invalid_cutoff:
        events.append(
            ValidationEvent(
                "ERROR",
                "invalid_cutoff_time",
                f"cutoff_time contains {invalid_cutoff} unparsable timestamps",
                "cutoff_time",
                invalid_cutoff,
            )
        )
    if invalid_target:
        events.append(
            ValidationEvent(
                "ERROR",
                "invalid_target_time",
                f"target_time contains {invalid_target} unparsable timestamps",
                "target_time",
                invalid_target,
            )
        )
    if invalid_cutoff or invalid_target:
        return events

    not_future = target <= cutoff
    if bool(not_future.any()) and not allow_insample:
        count = int(not_future.sum())
        events.append(
            ValidationEvent(
                "ERROR",
                "target_not_after_cutoff",
                f"{count} rows have target_time at or before cutoff_time",
                "target_time",
                count,
                _sample_rows(frame[not_future]),
            )
        )
    elif bool(not_future.any()):
        events.append(
            ValidationEvent(
                "WARN",
                "insample_targets",
                "In-sample target times were accepted because allow_insample=True",
                "target_time",
                int(not_future.sum()),
            )
        )

    if _timezone_naive(cutoff) or _timezone_naive(target):
        events.append(
            ValidationEvent(
                "WARN",
                "timezone_naive",
                "cutoff_time or target_time is timezone-naive; timezone-aware timestamps are safer",
            )
        )
    return events


def _duplicate_checks(frame: pd.DataFrame) -> list[ValidationEvent]:
    keys = ["run_id", "series_id", "cutoff_time", "target_time"]
    duplicates = frame.duplicated(keys, keep=False)
    if not bool(duplicates.any()):
        return []
    count = int(duplicates.sum())
    return [
        ValidationEvent(
            "ERROR",
            "duplicate_keys",
            f"{count} duplicate forecast points for run_id/series_id/cutoff_time/target_time",
            affected_count=count,
            sample=_sample_rows(frame[duplicates]),
        )
    ]


def _finite_checks(frame: pd.DataFrame) -> list[ValidationEvent]:
    events: list[ValidationEvent] = []
    for column, severity in [("yhat", "ERROR"), ("actual", "WARN"), ("benchmark_yhat", "WARN")]:
        if column not in frame:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        invalid = numeric.notna() & ~np.isfinite(numeric)
        missing_after_present = frame[column].notna() & numeric.isna()
        count = int((invalid | missing_after_present).sum())
        if count:
            events.append(
                ValidationEvent(
                    severity,
                    f"non_finite_{column}",
                    f"{column} contains {count} non-finite values",
                    column,
                    count,
                    _sample_rows(frame[invalid | missing_after_present]),
                )
            )
    return events


def _interval_checks(frame: pd.DataFrame) -> list[ValidationEvent]:
    events: list[ValidationEvent] = []
    if {"yhat_lower", "yhat_upper"}.issubset(frame.columns):
        lower = pd.to_numeric(frame["yhat_lower"], errors="coerce")
        upper = pd.to_numeric(frame["yhat_upper"], errors="coerce")
        yhat = pd.to_numeric(frame["yhat"], errors="coerce")
        inverted = lower > upper
        outside = (lower > yhat) | (yhat > upper)
        if bool(inverted.any()):
            events.append(
                ValidationEvent(
                    "ERROR",
                    "interval_inverted",
                    "Some rows have yhat_lower greater than yhat_upper",
                    affected_count=int(inverted.sum()),
                    sample=_sample_rows(frame[inverted]),
                )
            )
        if bool(outside.any()):
            events.append(
                ValidationEvent(
                    "WARN",
                    "point_outside_interval",
                    "Some rows have yhat outside the prediction interval",
                    affected_count=int(outside.sum()),
                    sample=_sample_rows(frame[outside]),
                )
            )
    elif "yhat_lower" in frame or "yhat_upper" in frame:
        events.append(
            ValidationEvent(
                "WARN",
                "partial_interval",
                "Only one interval bound is present; coverage cannot be computed",
            )
        )
    return events


def _quantile_checks(frame: pd.DataFrame) -> list[ValidationEvent]:
    events: list[ValidationEvent] = []
    invalid_columns = [
        str(column)
        for column in frame.columns
        if QUANTILE_LIKE_COLUMN_PATTERN.fullmatch(str(column))
        and not QUANTILE_COLUMN_PATTERN.fullmatch(str(column))
    ]
    if invalid_columns:
        events.append(
            ValidationEvent(
                "ERROR",
                "invalid_quantile_columns",
                "Quantile forecast columns must use canonical names from yhat_p01 through yhat_p99",
                affected_count=len(invalid_columns),
                sample={"columns": invalid_columns[:5]},
            )
        )
    quantile_columns = sorted(
        [column for column in frame.columns if QUANTILE_COLUMN_PATTERN.fullmatch(column)],
        key=lambda column: int(column.replace("yhat_p", "")),
    )
    if len(quantile_columns) < 2:
        return events
    numeric = frame[quantile_columns].apply(pd.to_numeric, errors="coerce")
    monotonic = numeric.diff(axis=1).iloc[:, 1:] >= 0
    invalid = monotonic.notna().all(axis=1) & ~monotonic.all(axis=1)
    if not bool(invalid.any()):
        return events
    events.append(
        ValidationEvent(
            "ERROR",
            "quantiles_not_monotonic",
            "Quantile forecast columns are not monotonically increasing",
            affected_count=int(invalid.sum()),
            sample=_sample_rows(frame[invalid]),
        )
    )
    return events


def _actuals_checks(frame: pd.DataFrame) -> list[ValidationEvent]:
    events: list[ValidationEvent] = []
    if "actual" not in frame:
        return events
    missing = frame["actual"].isna()
    if bool(missing.any()):
        ratio = missing.mean()
        severity = "WARN" if ratio < 1 else "INFO"
        events.append(
            ValidationEvent(
                severity,
                "missing_actuals",
                f"{ratio:.0%} of rows are missing actuals",
                "actual",
                int(missing.sum()),
            )
        )
    if "actual_available_at" in frame:
        available_at = pd.to_datetime(frame["actual_available_at"], errors="coerce")
        cutoff = pd.to_datetime(frame["cutoff_time"], errors="coerce")
        leakage = available_at.notna() & (available_at <= cutoff)
        if bool(leakage.any()):
            events.append(
                ValidationEvent(
                    "WARN",
                    "actual_available_before_cutoff",
                    "Some actuals appear available at or before cutoff_time; inspect leakage risk",
                    "actual_available_at",
                    int(leakage.sum()),
                    _sample_rows(frame[leakage]),
                )
            )
    return events


def _cardinality_checks(frame: pd.DataFrame, *, max_slice_cardinality: int) -> list[ValidationEvent]:
    events: list[ValidationEvent] = []
    safe_slice_columns = [
        "region",
        "zone",
        "category",
        "weekday",
        "month",
        "holiday_flag",
        "event_present",
        "event_type",
        "series_group",
        "customer_segment",
    ]
    for column in safe_slice_columns:
        if column not in frame:
            continue
        unique_count = int(frame[column].nunique(dropna=True))
        if unique_count > max_slice_cardinality:
            events.append(
                ValidationEvent(
                    "WARN",
                    "slice_cardinality_high",
                    f"{column} has {unique_count} values; metric labels may be high-cardinality",
                    column,
                    unique_count,
                )
            )
    return events


def _timezone_naive(series: pd.Series) -> bool:
    try:
        dtype = series.dt.tz
        return dtype is None
    except (AttributeError, TypeError):
        return True


def _sample_rows(frame: pd.DataFrame, limit: int = 3) -> dict[str, Any] | None:
    if frame.empty:
        return None
    sample = frame.head(limit).copy()
    for column in sample.columns:
        sample[column] = sample[column].map(_json_safe)
    return {"rows": sample.to_dict(orient="records")}


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value):
        return None
    return value
