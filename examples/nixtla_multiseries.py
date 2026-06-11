from __future__ import annotations

import numpy as np
import pandas as pd

import forecastops as fops


rng = np.random.default_rng(12)
cutoff = pd.Timestamp("2026-04-30")
rows = []
for series in ["sku-001", "sku-002", "sku-003"]:
    for step, target in enumerate(pd.date_range(cutoff + pd.Timedelta(days=1), periods=14, freq="D"), 1):
        base = 80 + step * 0.8 + rng.normal(0, 1)
        rows.append(
            {
                "unique_id": series,
                "ds": target,
                "AutoARIMA": base,
                "ETS": base + rng.normal(0, 2),
                "actual": base + rng.normal(0, 3),
            }
        )
preds = pd.DataFrame(rows)

auto_run = fops.capture(
    preds,
    project="nixtla-demo",
    adapter="nixtla",
    model_col="AutoARIMA",
    cutoff=cutoff,
)
ets_run = fops.capture(
    preds,
    project="nixtla-demo",
    adapter="nixtla",
    model_col="ETS",
    cutoff=cutoff,
)

result = fops.diff(auto_run, ets_run)
print({"base": result.base_run_id, "candidate": result.candidate_run_id})
print(result.metric_deltas.head().to_string(index=False))

