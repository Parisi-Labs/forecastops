from __future__ import annotations

import pandas as pd

import forecastops as fops

from _synthetic import daily_demand


history = daily_demand(series_id="homepage")
cutoff = history["ds"].max()
future = pd.date_range(cutoff + pd.Timedelta(days=1), periods=30, freq="D")
baseline = history["y"].tail(14).mean()
forecast = pd.DataFrame(
    {
        "ds": future,
        "yhat": baseline,
        "yhat_lower": baseline - 12,
        "yhat_upper": baseline + 12,
    }
)
actuals = pd.DataFrame({"ds": future, "y": baseline + 3})

run = fops.capture(
    forecast,
    project="prophet-demo",
    series_id="homepage",
    cutoff=cutoff,
    actuals=actuals,
)

print({"run_id": run.run_id, "status": run.status})

