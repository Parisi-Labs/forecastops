from __future__ import annotations

from _synthetic import daily_demand, forecast_from_history

import forecastops as fops
from forecastops.core.report import report

history = daily_demand()
forecast_df, actuals_df = forecast_from_history(history)

run = fops.capture(
    forecast_df,
    project="demand",
    schema=fops.ForecastSchema(
        series_id="series_id",
        target_time="target_time",
        prediction="prediction",
        lower="yhat_lower",
        upper="yhat_upper",
        extra_columns=["region"],
    ),
    cutoff=history["ds"].max(),
    actuals=actuals_df,
    model_name="seasonal-baseline",
    model_version="2026.06",
)

report_path = report(run)
print({"run_id": run.run_id, "status": run.status, "report": str(report_path)})

