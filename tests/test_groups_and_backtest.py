from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import forecastops as fops
from forecastops.ui.queries import UIQueries


def _schema() -> fops.ForecastSchema:
    return fops.ForecastSchema(
        series_id="series_id", target_time="target_time", prediction="prediction"
    )


def test_capture_group_membership(isolated_store: Path) -> None:
    for value in (1.0, 2.0):
        fops.capture(
            pd.DataFrame(
                {
                    "series_id": ["s", "s"],
                    "target_time": pd.date_range("2026-01-02", periods=2, freq="D"),
                    "prediction": [value, value + 1],
                }
            ),
            project="exp",
            schema=_schema(),
            cutoff=pd.Timestamp("2026-01-01"),
            group="variant-sweep",
            store=isolated_store,
        )

    groups = UIQueries(isolated_store).groups()
    assert len(groups) == 1
    assert groups[0]["name"] == "variant-sweep"
    assert groups[0]["run_count"] == 2
    assert groups[0]["kind"] == "experiment"

    runs = UIQueries(isolated_store).runs()
    assert all(run["group_id"] == "exp::variant-sweep" for run in runs)


def _panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    windows = []
    actuals = []
    for cutoff, start in [
        (pd.Timestamp("2026-01-01"), "2026-01-02"),
        (pd.Timestamp("2026-01-08"), "2026-01-09"),
    ]:
        times = pd.date_range(start, periods=4, freq="D")
        windows.append(
            pd.DataFrame(
                {
                    "series_id": "s",
                    "cutoff": cutoff,
                    "target_time": times,
                    "prediction": [10.0, 11.0, 12.0, 13.0],
                }
            )
        )
        actuals.append(pd.DataFrame({"target_time": times, "actual": [10.5, 10.5, 12.5, 12.5]}))
    return pd.concat(windows, ignore_index=True), pd.concat(actuals, ignore_index=True)


def test_backtest_creates_grouped_runs(isolated_store: Path) -> None:
    forecast, actuals = _panel()

    result = fops.backtest(
        forecast,
        group="rolling",
        project="bt",
        schema=_schema(),
        actuals=actuals,
        cutoff_col="cutoff",
        store=isolated_store,
    )

    assert result.windows == 2
    assert result.group_id == "bt::rolling"
    assert not result.per_cutoff.empty
    mae_row = result.aggregate[result.aggregate["metric_name"] == "mae"]
    assert mae_row["count"].iloc[0] == 2
    assert mae_row["mean"].iloc[0] > 0

    groups = {g["group_id"]: g for g in UIQueries(isolated_store).groups()}
    assert groups["bt::rolling"]["kind"] == "backtest"
    assert groups["bt::rolling"]["run_count"] == 2


def test_backtest_requires_min_windows(isolated_store: Path) -> None:
    forecast, actuals = _panel()
    single = forecast[forecast["cutoff"] == pd.Timestamp("2026-01-01")]
    with pytest.raises(ValueError, match="at least 2 distinct"):
        fops.backtest(
            single,
            group="rolling",
            project="bt",
            schema=_schema(),
            actuals=actuals,
            store=isolated_store,
        )


def test_backtest_missing_cutoff_column(isolated_store: Path) -> None:
    with pytest.raises(ValueError, match="rolling-origin column"):
        fops.backtest(
            pd.DataFrame({"series_id": ["s"], "target_time": ["2026-01-02"], "prediction": [1.0]}),
            group="rolling",
            project="bt",
            schema=_schema(),
            store=isolated_store,
        )
