from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from forecastops.core.evaluate import (
    DEFAULT_METRICS,
    EvaluationResult,
    align_merge_times,
    compute_metrics,
    ensure_unique_merge_keys,
    prepare_evaluation_frame,
    resolve_default_series_id,
    resolve_frame_run_id,
)
from forecastops.core.run import ForecastRun, MetricRecord, utc_now
from forecastops.store.parquet import read_artifact

LOSS_METRICS = {"mae", "rmse", "wape"}


@dataclass(slots=True)
class ComparisonResult:
    metrics: list[MetricRecord]
    frame: pd.DataFrame

    def to_frame(self) -> pd.DataFrame:
        return EvaluationResult(self.metrics, self.frame).to_frame()


def compare(
    run: ForecastRun | pd.DataFrame | str | Path,
    *,
    benchmark: pd.DataFrame | None = None,
    benchmark_name: str = "benchmark",
    metrics: list[str] | None = None,
    slices: list[str] | None = None,
    run_id: str | None = None,
    max_slice_cardinality: int = 100,
) -> ComparisonResult:
    frame, run_id = _resolve_run_frame(run, run_id=run_id)
    if benchmark is not None:
        frame = attach_benchmark(frame, benchmark, benchmark_name=benchmark_name)
    if "benchmark_yhat" not in frame:
        raise ValueError("benchmark_yhat is required for benchmark comparison")

    selected_metrics = list(metrics or DEFAULT_METRICS)
    benchmark_side_metrics = [metric for metric in selected_metrics if metric != "count"]
    model_frame = prepare_evaluation_frame(frame)
    benchmark_frame = frame.copy()
    benchmark_frame["yhat"] = benchmark_frame["benchmark_yhat"]
    benchmark_frame = prepare_evaluation_frame(benchmark_frame)

    model_metrics = compute_metrics(
        model_frame,
        run_id=run_id,
        metrics=selected_metrics,
        slices=slices or ["horizon_bucket"],
        max_slice_cardinality=max_slice_cardinality,
    )
    benchmark_metrics = compute_metrics(
        benchmark_frame,
        run_id=run_id,
        metrics=benchmark_side_metrics,
        slices=slices or ["horizon_bucket"],
        max_slice_cardinality=max_slice_cardinality,
        benchmark_name=benchmark_name,
    )
    skill_metrics = _skill_metrics(run_id, model_metrics, benchmark_metrics, benchmark_name)
    return ComparisonResult(metrics=[*model_metrics, *benchmark_metrics, *skill_metrics], frame=model_frame)


def attach_benchmark(
    frame: pd.DataFrame,
    benchmark: pd.DataFrame,
    *,
    benchmark_name: str = "benchmark",
) -> pd.DataFrame:
    default_series = resolve_default_series_id(frame)
    benchmark_frame = _normalize_benchmark(benchmark, benchmark_name, default_series_id=default_series)
    keys = ["series_id", "target_time"]
    if "cutoff_time" in benchmark_frame and benchmark_frame["cutoff_time"].notna().any():
        keys = ["series_id", "cutoff_time", "target_time"]
    base = frame.drop(
        columns=["benchmark_yhat", "benchmark_name", "benchmark_version"],
        errors="ignore",
    )
    base, benchmark_frame = align_merge_times(base, benchmark_frame)
    ensure_unique_merge_keys(benchmark_frame, keys, label="benchmark")
    merged = base.merge(
        benchmark_frame,
        on=keys,
        how="left",
        suffixes=("", "_benchmark"),
        validate="m:1",
    )
    if (
        not merged.empty
        and benchmark_frame["benchmark_yhat"].notna().any()
        and not merged["benchmark_yhat"].notna().any()
    ):
        warnings.warn(
            "attach_benchmark matched zero forecast rows; "
            "check series_id and timestamp alignment between forecast and benchmark",
            UserWarning,
            stacklevel=2,
        )
    return merged


def _normalize_benchmark(
    benchmark: pd.DataFrame,
    benchmark_name: str,
    default_series_id: str = "default",
) -> pd.DataFrame:
    out = benchmark.copy()
    rename: dict[str, str] = {}
    if "series_id" not in out and "unique_id" in out:
        rename["unique_id"] = "series_id"
    if "target_time" not in out and "ds" in out:
        rename["ds"] = "target_time"
    if "benchmark_yhat" not in out:
        for candidate in ["yhat", "prediction", "forecast", "benchmark"]:
            if candidate in out:
                rename[candidate] = "benchmark_yhat"
                break
    out = out.rename(columns=rename)
    if "series_id" not in out:
        out["series_id"] = default_series_id
    if "benchmark_name" not in out:
        out["benchmark_name"] = benchmark_name
    keep = [
        column
        for column in [
            "series_id",
            "cutoff_time",
            "target_time",
            "benchmark_yhat",
            "benchmark_name",
            "benchmark_version",
        ]
        if column in out
    ]
    out = out[keep]
    for column in ["cutoff_time", "target_time"]:
        if column in out:
            out[column] = pd.to_datetime(out[column], errors="coerce")
    out["benchmark_yhat"] = pd.to_numeric(out["benchmark_yhat"], errors="coerce")
    return out


def _skill_metrics(
    run_id: str,
    model_metrics: list[MetricRecord],
    benchmark_metrics: list[MetricRecord],
    benchmark_name: str,
) -> list[MetricRecord]:
    benchmark_lookup = {
        (metric.metric_name, metric.slice_name, metric.slice_value): metric
        for metric in benchmark_metrics
        if metric.metric_name in LOSS_METRICS
    }
    skill: list[MetricRecord] = []
    for metric in model_metrics:
        if metric.metric_name not in LOSS_METRICS:
            continue
        benchmark_metric = benchmark_lookup.get((metric.metric_name, metric.slice_name, metric.slice_value))
        if not benchmark_metric or benchmark_metric.metric_value == 0:
            continue
        value = 1 - (metric.metric_value / benchmark_metric.metric_value)
        skill.append(
            MetricRecord(
                metric_id=(
                    f"{run_id}:skill_{metric.metric_name}:"
                    f"{metric.slice_name or 'overall'}:{metric.slice_value or 'all'}"
                ),
                run_id=run_id,
                metric_name=f"skill_{metric.metric_name}",
                metric_value=float(value),
                benchmark_name=benchmark_name,
                horizon_bucket=metric.horizon_bucket,
                slice_name=metric.slice_name,
                slice_value=metric.slice_value,
                series_group=metric.series_group,
                points_count=metric.points_count,
                created_at=utc_now(),
            )
        )
    return skill


def _resolve_run_frame(
    run: ForecastRun | pd.DataFrame | str | Path,
    *,
    run_id: str | None = None,
) -> tuple[pd.DataFrame, str]:
    if isinstance(run, ForecastRun):
        return read_artifact(run.forecast_artifact_uri), run.run_id
    if isinstance(run, pd.DataFrame):
        return run.copy(), resolve_frame_run_id(run, run_id)
    frame = read_artifact(run)
    return frame, resolve_frame_run_id(frame, run_id)
