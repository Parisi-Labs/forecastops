from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from forecastops.adapters.base import ForecastAdapter
from forecastops.core.normalize import normalize_dataframe
from forecastops.core.run import CaptureContext, DetectionResult, NormalizedForecast
from forecastops.core.schema import ForecastSchema


class DartsAdapter(ForecastAdapter):
    name = "darts"

    def detect(self, obj: Any) -> DetectionResult:
        objects = obj if isinstance(obj, list) else [obj]
        matched = bool(objects) and all(
            hasattr(item, "time_index") and (hasattr(item, "values") or hasattr(item, "pd_dataframe"))
            for item in objects
        )
        return DetectionResult(
            matched,
            0.75 if matched else 0.0,
            "Darts TimeSeries-like object" if matched else "not a Darts TimeSeries-like object",
        )

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        objects = obj if isinstance(obj, list) else [obj]
        rows: list[pd.DataFrame] = []
        for index, series in enumerate(objects):
            if hasattr(series, "pd_dataframe"):
                values = series.pd_dataframe()
                if isinstance(values, pd.DataFrame):
                    value_column = values.columns[0]
                    frame = values.reset_index().rename(columns={values.index.name or "index": "target_time"})
                    frame["prediction"] = frame[value_column]
                else:
                    raise ValueError("Darts pd_dataframe() did not return a pandas DataFrame")
            else:
                frame = pd.DataFrame(
                    {
                        "target_time": list(series.time_index),
                        "prediction": np.asarray(series.values()).reshape(-1),
                    }
                )
            frame["series_id"] = (
                context.series_id[index]
                if isinstance(context.series_id, list) and index < len(context.series_id)
                else getattr(series, "components", [None])[0]
                if hasattr(series, "components")
                else context.series_id or f"series_{index}"
            )
            rows.append(frame[["series_id", "target_time", "prediction"]])
        df = pd.concat(rows, ignore_index=True)
        context.model_name = context.model_name or "darts"
        schema = ForecastSchema(series_id="series_id", target_time="target_time", prediction="prediction")
        return normalize_dataframe(df, context=context, adapter_name=self.name, schema=schema)

