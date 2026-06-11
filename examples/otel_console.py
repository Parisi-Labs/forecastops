from __future__ import annotations

import os

import forecastops as fops

from _synthetic import daily_demand, forecast_from_history


os.environ["FOPS_OTEL_ENABLED"] = "true"

history = daily_demand(series_id="telemetry-demo")
forecast_df, actuals_df = forecast_from_history(history)

run = fops.capture(
    forecast_df,
    project="otel-demo",
    schema=fops.ForecastSchema(
        series_id="series_id",
        target_time="target_time",
        prediction="prediction",
        lower="yhat_lower",
        upper="yhat_upper",
    ),
    cutoff=history["ds"].max(),
    actuals=actuals_df,
    model_name="seasonal-baseline",
)

print({"run_id": run.run_id, "trace_id": run.trace_id, "metrics": len(run.metrics)})

