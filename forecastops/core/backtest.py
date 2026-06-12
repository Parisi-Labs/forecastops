from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from forecastops.core.capture import capture
from forecastops.core.run import ForecastRun, make_group_id
from forecastops.core.schema import ForecastSchema


@dataclass(slots=True)
class BacktestResult:
    """The outcome of a rolling-origin backtest: a group of per-cutoff runs."""

    group_id: str
    group: str
    runs: list[ForecastRun]
    per_cutoff: pd.DataFrame  # cutoff, run_id, metric_name, metric_value
    aggregate: pd.DataFrame  # metric_name, mean, std, count

    @property
    def windows(self) -> int:
        return len(self.runs)


def backtest(
    forecast: pd.DataFrame,
    *,
    group: str,
    project: str = "default",
    schema: ForecastSchema | dict[str, Any] | None = None,
    actuals: pd.DataFrame | None = None,
    cutoff_col: str = "cutoff",
    min_windows: int = 2,
    store: str | Path | None = None,
    **capture_kwargs: Any,
) -> BacktestResult:
    """Evaluate a rolling-origin forecast panel as a grouped backtest.

    ``forecast`` is a panel that already contains forecasts produced at several
    origins, identified by ``cutoff_col``. Each distinct origin is captured as its
    own run, all sharing one backtest group, and metrics are aggregated across the
    windows. ForecastOps does not retrain models — produce the rolling forecasts
    with your own workflow, then hand the panel here.
    """
    if cutoff_col not in forecast.columns:
        raise ValueError(
            f"backtest expects a rolling-origin column {cutoff_col!r}; "
            f"available columns: {list(forecast.columns)}"
        )
    schema_obj = schema if isinstance(schema, ForecastSchema) else ForecastSchema.from_dict(schema)
    cutoffs = list(pd.Series(forecast[cutoff_col].dropna().unique()))
    if len(cutoffs) < min_windows:
        raise ValueError(
            f"backtest needs at least {min_windows} distinct {cutoff_col!r} values, "
            f"found {len(cutoffs)}"
        )

    group_id = make_group_id(project, group)
    runs: list[ForecastRun] = []
    rows: list[dict[str, Any]] = []
    for cutoff in sorted(cutoffs):
        window = forecast[forecast[cutoff_col] == cutoff].drop(columns=[cutoff_col])
        run = capture(
            window,
            project=project,
            schema=schema_obj,
            cutoff=cutoff,
            actuals=actuals,
            group=group,
            group_kind="backtest",
            run_name=f"cutoff={cutoff}",
            store=store,
            **capture_kwargs,
        )
        runs.append(run)
        for metric in run.metrics:
            if metric.slice_name is None and metric.benchmark_name is None:
                rows.append(
                    {
                        "cutoff": cutoff,
                        "run_id": run.run_id,
                        "metric_name": metric.metric_name,
                        "metric_value": metric.metric_value,
                    }
                )

    per_cutoff = pd.DataFrame(rows, columns=["cutoff", "run_id", "metric_name", "metric_value"])
    if per_cutoff.empty:
        aggregate = pd.DataFrame(columns=["metric_name", "mean", "std", "count"])
    else:
        aggregate = (
            per_cutoff.groupby("metric_name")["metric_value"]
            .agg(["mean", "std", "count"])
            .reset_index()
        )
    return BacktestResult(
        group_id=group_id,
        group=group,
        runs=runs,
        per_cutoff=per_cutoff,
        aggregate=aggregate,
    )
