from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from forecastops.core.run import ForecastRun, MetricRecord, utc_now
from forecastops.store.parquet import read_artifact

DEFAULT_METRICS = [
    "mae",
    "rmse",
    "wape",
    "smape",
    "bias",
    "count",
    "coverage",
    "interval_width",
    "pinball",
]

# Canonical quantile prediction columns, e.g. yhat_p05, yhat_p90.
_QUANTILE_COLUMN = re.compile(r"yhat_p(0[1-9]|[1-9]\d)")

# Metrics that need observed actuals; skipped (returning None) when actuals are absent.
_ACTUAL_METRICS = {"mae", "rmse", "wape", "smape", "bias", "coverage", "pinball"}


@dataclass(slots=True)
class EvaluationResult:
    metrics: list[MetricRecord]
    frame: pd.DataFrame

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "metric_name": metric.metric_name,
                    "metric_value": metric.metric_value,
                    "points_count": metric.points_count,
                    "benchmark_name": metric.benchmark_name,
                    "horizon_bucket": metric.horizon_bucket,
                    "slice_name": metric.slice_name,
                    "slice_value": metric.slice_value,
                    "series_group": metric.series_group,
                }
                for metric in self.metrics
            ]
        )


def evaluate(
    forecast: ForecastRun | pd.DataFrame | str | Path,
    *,
    actuals: pd.DataFrame | None = None,
    metrics: list[str] | None = None,
    slices: list[str] | None = None,
    run_id: str | None = None,
    max_slice_cardinality: int = 100,
) -> EvaluationResult:
    frame, resolved_run_id = _resolve_forecast_frame(forecast, run_id=run_id)
    if actuals is not None:
        frame = attach_actuals(frame, actuals)
    prepared = prepare_evaluation_frame(frame)
    selected_metrics = metrics or DEFAULT_METRICS
    metric_records = compute_metrics(
        prepared,
        run_id=resolved_run_id,
        metrics=selected_metrics,
        slices=slices or ["horizon_bucket"],
        max_slice_cardinality=max_slice_cardinality,
    )
    return EvaluationResult(metrics=metric_records, frame=prepared)


def attach_actuals(frame: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
    default_series = resolve_default_series_id(frame)
    actual_frame = _normalize_actuals(actuals, default_series_id=default_series)
    keys = ["series_id", "target_time"]
    if "cutoff_time" in actual_frame and actual_frame["cutoff_time"].notna().any():
        keys = ["series_id", "cutoff_time", "target_time"]
    base = frame.drop(columns=["actual"], errors="ignore")
    base, actual_frame = align_merge_times(base, actual_frame)
    ensure_unique_merge_keys(actual_frame, keys, label="actuals")
    merged = base.merge(actual_frame, on=keys, how="left", suffixes=("", "_actuals"), validate="m:1")
    if (
        "actual" in merged
        and not merged.empty
        and "actual" in actual_frame
        and actual_frame["actual"].notna().any()
        and not merged["actual"].notna().any()
    ):
        warnings.warn(
            "attach_actuals matched zero forecast rows; "
            "check series_id and timestamp alignment between forecast and actuals",
            UserWarning,
            stacklevel=2,
        )
    return merged


def resolve_default_series_id(frame: pd.DataFrame) -> str:
    """Series id used for actuals/benchmark frames that carry no series column."""
    if "series_id" in frame and frame["series_id"].nunique(dropna=True) == 1:
        return str(frame["series_id"].dropna().iloc[0])
    return "default"


def align_merge_times(
    left: pd.DataFrame,
    right: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Coerce time columns to a consistent timezone convention before merging.

    If any time column on either side is timezone-aware, every time column on both
    sides is converted to UTC (naive values are assumed to be UTC); otherwise all
    stay naive. Without this, tz-aware vs tz-naive keys silently match zero rows.
    """
    left = left.copy()
    right = right.copy()
    frames = (left, right)
    converted: dict[tuple[int, str], pd.Series] = {}
    any_aware = False
    for index, frame in enumerate(frames):
        for column in ("cutoff_time", "target_time"):
            if column not in frame.columns:
                continue
            values = pd.to_datetime(frame[column], errors="coerce")
            if not pd.api.types.is_datetime64_any_dtype(values):
                continue
            converted[(index, column)] = values
            any_aware = any_aware or values.dt.tz is not None
    for (index, column), values in converted.items():
        if any_aware:
            values = (
                values.dt.tz_localize("UTC")
                if values.dt.tz is None
                else values.dt.tz_convert("UTC")
            )
        frames[index][column] = values
    return left, right


def ensure_unique_merge_keys(frame: pd.DataFrame, keys: list[str], *, label: str) -> None:
    """Raise a clear error when a right-hand merge frame has duplicate join keys."""
    duplicated = frame.duplicated(keys, keep=False)
    if not bool(duplicated.any()):
        return
    sample = frame.loc[duplicated, keys].drop_duplicates().head(5)
    raise ValueError(
        f"{label} contains duplicate rows for merge keys {keys}; duplicates would fan out the "
        f"forecast frame and double-count metrics. Duplicated keys (sample): "
        f"{sample.to_dict(orient='records')}"
    )


def prepare_evaluation_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "actual" in out:
        out["error"] = pd.to_numeric(out["yhat"], errors="coerce") - pd.to_numeric(
            out["actual"], errors="coerce"
        )
        out["abs_error"] = out["error"].abs()
        out["squared_error"] = out["error"] ** 2
    out["horizon_bucket"] = out.apply(_horizon_bucket, axis=1)
    if "target_time" in out:
        target = pd.to_datetime(out["target_time"], errors="coerce")
        out["weekday"] = out.get("weekday", target.dt.day_name())
        out["month"] = out.get("month", target.dt.month.astype("Int64").astype("string"))
    return out


def compute_metrics(
    frame: pd.DataFrame,
    *,
    run_id: str,
    metrics: list[str],
    slices: list[str],
    max_slice_cardinality: int = 100,
    benchmark_name: str | None = None,
) -> list[MetricRecord]:
    records: list[MetricRecord] = []
    groups: list[tuple[str | None, str | None, pd.DataFrame]] = [(None, None, frame)]
    for requested_slice in slices:
        if requested_slice not in frame:
            continue
        if frame[requested_slice].nunique(dropna=True) > max_slice_cardinality:
            continue
        for value, group in frame.groupby(requested_slice, dropna=False):
            groups.append((requested_slice, str(value), group))

    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for slice_name, slice_value, group in groups:
        horizon_bucket: str | None = slice_value if slice_name == "horizon_bucket" else None
        for metric_name in metrics:
            value = _metric_value(group, metric_name)
            if value is None or not np.isfinite(value):
                continue
            key = (metric_name, benchmark_name, slice_name, slice_value)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                MetricRecord(
                    metric_id=_metric_id(run_id, metric_name, benchmark_name, slice_name, slice_value),
                    run_id=run_id,
                    metric_name=metric_name,
                    metric_value=float(value),
                    benchmark_name=benchmark_name,
                    horizon_bucket=horizon_bucket,
                    slice_name=slice_name,
                    slice_value=slice_value,
                    series_group=slice_value if slice_name == "series_group" else None,
                    points_count=len(group),
                    created_at=utc_now(),
                )
            )
    return records


def _metric_value(frame: pd.DataFrame, metric_name: str) -> float | None:
    metric_name = metric_name.lower()
    has_actual = "actual" in frame and frame["actual"].notna().any()
    if metric_name == "count":
        return float(len(frame))
    if not has_actual and metric_name in _ACTUAL_METRICS:
        return None
    if metric_name == "mae":
        return float(frame["abs_error"].mean())
    if metric_name == "rmse":
        return float(np.sqrt(frame["squared_error"].mean()))
    if metric_name == "wape":
        denominator = pd.to_numeric(frame["actual"], errors="coerce").abs().sum()
        if denominator == 0:
            return None
        return float(frame["abs_error"].sum() / denominator)
    if metric_name == "smape":
        # Symmetric MAPE as a ratio in [0, 2] (consistent with wape, not a percentage).
        actual = pd.to_numeric(frame["actual"], errors="coerce")
        predicted = pd.to_numeric(frame["yhat"], errors="coerce")
        denominator = actual.abs() + predicted.abs()
        valid = actual.notna() & predicted.notna() & (denominator != 0)
        if not bool(valid.any()):
            return None
        return float((2.0 * (predicted[valid] - actual[valid]).abs() / denominator[valid]).mean())
    if metric_name == "pinball":
        return _pinball_loss(frame)
    if metric_name == "bias":
        return float(frame["error"].mean())
    if metric_name == "coverage":
        if not {"yhat_lower", "yhat_upper"}.issubset(frame.columns):
            return None
        actual = pd.to_numeric(frame["actual"], errors="coerce")
        lower = pd.to_numeric(frame["yhat_lower"], errors="coerce")
        upper = pd.to_numeric(frame["yhat_upper"], errors="coerce")
        valid = actual.notna() & lower.notna() & upper.notna()
        if not bool(valid.any()):
            return None
        return float(((actual >= lower) & (actual <= upper))[valid].mean())
    if metric_name == "interval_width":
        if not {"yhat_lower", "yhat_upper"}.issubset(frame.columns):
            return None
        width = pd.to_numeric(frame["yhat_upper"], errors="coerce") - pd.to_numeric(
            frame["yhat_lower"], errors="coerce"
        )
        return float(width.mean())
    return None


def _pinball_loss(frame: pd.DataFrame) -> float | None:
    """Mean pinball (quantile) loss averaged over every ``yhat_p<level>`` column.

    Returns ``None`` when the forecast carries no quantile columns, so the metric is
    simply skipped for point forecasts. Averaging the per-quantile pinball losses gives
    a single proper score for probabilistic forecasts.
    """
    actual = pd.to_numeric(frame["actual"], errors="coerce")
    losses: list[float] = []
    for column in frame.columns:
        match = _QUANTILE_COLUMN.fullmatch(str(column))
        if match is None:
            continue
        quantile = int(match.group(1)) / 100.0
        if not 0.0 < quantile < 1.0:
            continue
        predicted = pd.to_numeric(frame[column], errors="coerce")
        valid = actual.notna() & predicted.notna()
        if not bool(valid.any()):
            continue
        diff = actual[valid] - predicted[valid]
        losses.append(float(np.maximum(quantile * diff, (quantile - 1.0) * diff).mean()))
    if not losses:
        return None
    return float(np.mean(losses))


def _normalize_actuals(actuals: pd.DataFrame, default_series_id: str = "default") -> pd.DataFrame:
    out = actuals.copy()
    rename: dict[str, str] = {}
    if "series_id" not in out and "unique_id" in out:
        rename["unique_id"] = "series_id"
    if "target_time" not in out and "ds" in out:
        rename["ds"] = "target_time"
    if "actual" not in out:
        if "y" in out:
            rename["y"] = "actual"
        elif "value" in out:
            rename["value"] = "actual"
    out = out.rename(columns=rename)
    if "series_id" not in out:
        out["series_id"] = default_series_id
    keep = [
        column
        for column in ["series_id", "cutoff_time", "target_time", "actual", "actual_available_at"]
        if column in out
    ]
    out = out[keep]
    for column in ["cutoff_time", "target_time", "actual_available_at"]:
        if column in out:
            out[column] = pd.to_datetime(out[column], errors="coerce")
    if "actual" in out:
        out["actual"] = pd.to_numeric(out["actual"], errors="coerce")
    return out


def resolve_frame_run_id(frame: pd.DataFrame, run_id: str | None = None) -> str:
    """Resolve a run id for an ad-hoc frame, falling back to "adhoc" when absent."""
    if run_id:
        return run_id
    if "run_id" in frame.columns and not frame.empty and frame["run_id"].notna().any():
        return str(frame["run_id"].dropna().iloc[0])
    return "adhoc"


def _resolve_forecast_frame(
    forecast: ForecastRun | pd.DataFrame | str | Path,
    *,
    run_id: str | None,
) -> tuple[pd.DataFrame, str]:
    if isinstance(forecast, ForecastRun):
        return read_artifact(forecast.forecast_artifact_uri), forecast.run_id
    if isinstance(forecast, pd.DataFrame):
        return forecast.copy(), resolve_frame_run_id(forecast, run_id)
    path = Path(forecast)
    frame = read_artifact(path)
    return frame, resolve_frame_run_id(frame, run_id)


def _horizon_bucket(row: pd.Series) -> str:
    duration = pd.to_timedelta(row.get("target_time") - row.get("cutoff_time"), errors="coerce")
    if pd.isna(duration):
        return "unknown"
    hours = duration.total_seconds() / 3600
    if hours <= 1:
        return "0-1h"
    if hours <= 6:
        return "1-6h"
    if hours <= 24:
        return "6-24h"
    if hours <= 48:
        return "24-48h"
    if hours <= 24 * 7:
        return "48h-7d"
    return "7d+"


def _metric_id(
    run_id: str,
    metric_name: str,
    benchmark_name: str | None,
    slice_name: str | None,
    slice_value: str | None,
) -> str:
    parts = [run_id, metric_name]
    if benchmark_name:
        parts.append(f"benchmark={benchmark_name}")
    if slice_name:
        parts.extend([slice_name, slice_value or "null"])
    return ":".join(parts)
