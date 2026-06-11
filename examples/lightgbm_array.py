from __future__ import annotations

import numpy as np
import pandas as pd

import forecastops as fops

cutoff = pd.Timestamp("2026-05-01")
target_time = pd.date_range(cutoff + pd.Timedelta(hours=1), periods=24, freq="h")
preds = np.linspace(50, 60, len(target_time)) + np.sin(np.arange(len(target_time)))
actuals = pd.DataFrame(
    {
        "target_time": target_time,
        "actual": preds + np.random.default_rng(4).normal(0, 1.5, len(target_time)),
    }
)

run = fops.capture(
    preds,
    adapter="array",
    project="array-demo",
    series_id="meter-17",
    cutoff=cutoff,
    target_time=target_time,
    model_name="lightgbm",
    actuals=actuals,
)

print({"run_id": run.run_id, "status": run.status})

