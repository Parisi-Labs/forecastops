from __future__ import annotations

from _synthetic import daily_demand, forecast_from_history

import forecastops as fops

for region, seed in [("north", 1), ("south", 2), ("west", 3)]:
    history = daily_demand(series_id=f"sku-{region}", seed=seed)
    forecast_df, actuals_df = forecast_from_history(history, seed=seed + 20)
    forecast_df["region"] = region
    fops.capture(
        forecast_df,
        project="ui-demo",
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
        model_version=f"region-{region}",
    )

print("Run: fops ui")

