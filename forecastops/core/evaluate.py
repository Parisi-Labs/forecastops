from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from forecastops.core.run import ForecastRun, MetricRecord, utc_now
from forecastops.store.parquet import read_artifact

DEFAULT_METRICS = ["mae", "rmse", "wape", "bias", "count", "coverage", "interval_width"]


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
    default_series = (
        str(frame["series_id"].dropna().iloc[0])
        if "series_id" in frame and frame["series_id"].nunique(dropna=True) == 1
        else "default"
    )
    actual_frame = _normalize_actuals(actuals, default_series_id=default_series)
    keys = ["series_id", "target_time"]
    if "cutoff_time" in actual_frame and actual_frame["cutoff_time"].notna().any():
        keys = ["series_id", "cutoff_time", "target_time"]
    base = frame.drop(columns=["actual"], errors="ignore")
    return base.merge(actual_frame, on=keys, how="left", suffixes=("", "_actuals"))


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
    for slice_name in slices:
        if slice_name not in frame:
            continue
        if frame[slice_name].nunique(dropna=True) > max_slice_cardinality:
            continue
        for value, group in frame.groupby(slice_name, dropna=False):
            groups.append((slice_name, str(value), group))

    seen: set[tuple[str, str | None, str | None, str | None]] = set()
    for slice_name, slice_value, group in groups:
        horizon_bucket = slice_value if slice_name == "horizon_bucket" else None
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
                    points_count=int(len(group)),
                    created_at=utc_now(),
                )
            )
    return records


def _metric_value(frame: pd.DataFrame, metric_name: str) -> float | None:
    metric_name = metric_name.lower()
    has_actual = "actual" in frame and frame["actual"].notna().any()
    if metric_name == "count":
        return float(len(frame))
    if not has_actual and metric_name in {"mae", "rmse", "wape", "bias", "coverage"}:
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


def _resolve_forecast_frame(
    forecast: ForecastRun | pd.DataFrame | str | Path,
    *,
    run_id: str | None,
) -> tuple[pd.DataFrame, str]:
    if isinstance(forecast, ForecastRun):
        return read_artifact(forecast.forecast_artifact_uri), forecast.run_id
    if isinstance(forecast, pd.DataFrame):
        return forecast.copy(), run_id or str(forecast["run_id"].iloc[0])
    path = Path(forecast)
    frame = read_artifact(path)
    return frame, run_id or str(frame["run_id"].iloc[0])


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
