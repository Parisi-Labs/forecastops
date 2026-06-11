from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from forecastops.adapters.base import ForecastAdapter
from forecastops.core.normalize import normalize_dataframe
from forecastops.core.run import CaptureContext, DetectionResult, NormalizedForecast
from forecastops.core.schema import ForecastSchema


class GluonTSAdapter(ForecastAdapter):
    name = "gluonts"

    def detect(self, obj: Any) -> DetectionResult:
        objects = obj if isinstance(obj, list) else [obj]
        matched = bool(objects) and all(
            hasattr(item, "start_date")
            and hasattr(item, "prediction_length")
            and (hasattr(item, "quantile") or hasattr(item, "samples"))
            for item in objects
        )
        return DetectionResult(
            matched,
            0.75 if matched else 0.0,
            "GluonTS Forecast-like object" if matched else "not a GluonTS Forecast-like object",
        )

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        objects = obj if isinstance(obj, list) else [obj]
        frames = []
        for index, forecast in enumerate(objects):
            prediction_length = int(forecast.prediction_length)
            freq = getattr(forecast, "freq", None) or getattr(forecast.start_date, "freqstr", None) or "D"
            start = pd.Timestamp(forecast.start_date)
            target_time = pd.date_range(start=start, periods=prediction_length, freq=freq)
            frame = pd.DataFrame({"target_time": target_time})
            frame["series_id"] = getattr(forecast, "item_id", None) or context.series_id or f"item_{index}"
            quantiles: dict[float, str] = {}
            if hasattr(forecast, "quantile"):
                for quantile in [0.1, 0.5, 0.9]:
                    column = f"q{int(quantile * 100)}"
                    frame[column] = np.asarray(forecast.quantile(quantile)).reshape(-1)
                    quantiles[quantile] = column
                frame["prediction"] = frame["q50"]
            else:
                samples = np.asarray(forecast.samples)
                frame["prediction"] = np.median(samples, axis=0).reshape(-1)
                frame["q10"] = np.quantile(samples, 0.1, axis=0).reshape(-1)
                frame["q90"] = np.quantile(samples, 0.9, axis=0).reshape(-1)
                quantiles = {0.1: "q10", 0.5: "prediction", 0.9: "q90"}
            frames.append(frame)
        df = pd.concat(frames, ignore_index=True)
        context.model_name = context.model_name or "gluonts"
        schema = ForecastSchema(
            series_id="series_id",
            target_time="target_time",
            prediction="prediction",
            quantiles=quantiles,
        )
        return normalize_dataframe(df, context=context, adapter_name=self.name, schema=schema)

