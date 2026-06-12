from __future__ import annotations

import pandas as pd

from forecastops.core.compare import compare


def _frame() -> pd.DataFrame:
    times = pd.date_range("2026-01-02", periods=4, freq="D")
    return pd.DataFrame(
        {
            "run_id": "r",
            "series_id": "s",
            "cutoff_time": pd.Timestamp("2026-01-01"),
            "target_time": times,
            "yhat": [10.0, 11.0, 12.0, 13.0],
            "actual": [10.5, 10.5, 12.5, 12.5],
            "benchmark_yhat": [9.0, 9.0, 9.0, 9.0],
            # Model quantile columns — these must NOT be reused for the benchmark.
            "yhat_p10": [8.0, 9.0, 10.0, 11.0],
            "yhat_p90": [12.0, 13.0, 14.0, 15.0],
        }
    )


def test_benchmark_side_has_no_pinball() -> None:
    metrics = compare(_frame(), run_id="r").metrics
    benchmark_pinball = [
        m for m in metrics if m.metric_name == "pinball" and m.benchmark_name is not None
    ]
    assert benchmark_pinball == []  # benchmark has no quantiles → no benchmark pinball

    # The model's pinball is still reported (model side, no benchmark_name).
    model_pinball = [m for m in metrics if m.metric_name == "pinball" and m.benchmark_name is None]
    assert model_pinball


def test_smape_gets_a_skill_metric() -> None:
    names = {m.metric_name for m in compare(_frame(), run_id="r").metrics}
    assert "skill_smape" in names
    assert "skill_mae" in names
    # No skill_pinball until real benchmark quantiles exist.
    assert "skill_pinball" not in names
