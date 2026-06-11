from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from forecastops.core.evaluate import evaluate
from forecastops.core.run import ForecastRun
from forecastops.store.parquet import read_artifact


@dataclass(slots=True)
class DiffResult:
    base_run_id: str
    candidate_run_id: str
    metric_deltas: pd.DataFrame
    forecast_deltas: pd.DataFrame
    regressions: pd.DataFrame


def diff(
    run_a: ForecastRun | pd.DataFrame | str | Path,
    run_b: ForecastRun | pd.DataFrame | str | Path,
    *,
    metrics: list[str] | None = None,
    slices: list[str] | None = None,
) -> DiffResult:
    base_frame, base_run_id = _frame_and_id(run_a)
    candidate_frame, candidate_run_id = _frame_and_id(run_b)
    base_metrics = evaluate(base_frame, run_id=base_run_id, metrics=metrics, slices=slices).to_frame()
    candidate_metrics = evaluate(
        candidate_frame,
        run_id=candidate_run_id,
        metrics=metrics,
        slices=slices,
    ).to_frame()
    metric_deltas = base_metrics.merge(
        candidate_metrics,
        on=["metric_name", "horizon_bucket", "slice_name", "slice_value", "benchmark_name"],
        how="outer",
        suffixes=("_base", "_candidate"),
    )
    metric_deltas["delta"] = metric_deltas["metric_value_candidate"] - metric_deltas["metric_value_base"]
    forecast_deltas = _forecast_deltas(base_frame, candidate_frame)
    regressions = metric_deltas[
        metric_deltas["metric_name"].isin(["mae", "rmse", "wape"])
        & (metric_deltas["delta"] > 0)
    ].sort_values("delta", ascending=False)
    return DiffResult(
        base_run_id=base_run_id,
        candidate_run_id=candidate_run_id,
        metric_deltas=metric_deltas,
        forecast_deltas=forecast_deltas,
        regressions=regressions,
    )


def _frame_and_id(run: ForecastRun | pd.DataFrame | str | Path) -> tuple[pd.DataFrame, str]:
    if isinstance(run, ForecastRun):
        return read_artifact(run.forecast_artifact_uri), run.run_id
    if isinstance(run, pd.DataFrame):
        return run.copy(), str(run["run_id"].iloc[0])
    frame = read_artifact(run)
    return frame, str(frame["run_id"].iloc[0])


def _forecast_deltas(base: pd.DataFrame, candidate: pd.DataFrame) -> pd.DataFrame:
    keys = ["series_id", "cutoff_time", "target_time"]
    merged = base[[*keys, "yhat"]].merge(
        candidate[[*keys, "yhat"]],
        on=keys,
        how="inner",
        suffixes=("_base", "_candidate"),
    )
    merged["forecast_delta"] = merged["yhat_candidate"] - merged["yhat_base"]
    merged["abs_forecast_delta"] = merged["forecast_delta"].abs()
    return merged.sort_values("abs_forecast_delta", ascending=False)
