from __future__ import annotations

import numpy as np
import pandas as pd


def daily_demand(periods: int = 90, *, series_id: str = "sku-001", seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ds = pd.date_range("2026-01-01", periods=periods, freq="D")
    trend = np.linspace(100, 120, periods)
    seasonality = 12 * np.sin(np.arange(periods) / 7 * 2 * np.pi)
    noise = rng.normal(0, 3, periods)
    return pd.DataFrame({"series_id": series_id, "ds": ds, "y": trend + seasonality + noise})


def forecast_from_history(history: pd.DataFrame, horizon: int = 21, *, seed: int = 9) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    cutoff = history["ds"].max()
    future_ds = pd.date_range(cutoff + pd.Timedelta(days=1), periods=horizon, freq="D")
    base = history["y"].tail(14).mean()
    seasonal = 10 * np.sin((np.arange(horizon) + len(history)) / 7 * 2 * np.pi)
    yhat = base + seasonal + np.linspace(0, 4, horizon)
    actual = yhat + rng.normal(0, 4, horizon)
    forecast = pd.DataFrame(
        {
            "series_id": history["series_id"].iloc[0],
            "target_time": future_ds,
            "prediction": yhat,
            "yhat_lower": yhat - 9,
            "yhat_upper": yhat + 9,
            "region": "north",
        }
    )
    actuals = pd.DataFrame(
        {
            "series_id": history["series_id"].iloc[0],
            "target_time": future_ds,
            "actual": actual,
        }
    )
    return forecast, actuals

