from __future__ import annotations

from typing import Any

import pandas as pd

from forecastops.adapters.base import ForecastAdapter
from forecastops.core.normalize import normalize_dataframe
from forecastops.core.run import CaptureContext, DetectionResult, NormalizedForecast
from forecastops.core.schema import ForecastSchema


class ProphetAdapter(ForecastAdapter):
    name = "prophet"

    def detect(self, obj: Any) -> DetectionResult:
        if not isinstance(obj, pd.DataFrame):
            return DetectionResult(False, 0.0, "object is not a pandas DataFrame")
        columns = set(obj.columns)
        matched = {"ds", "yhat"}.issubset(columns)
        confidence = 0.95 if matched and {"yhat_lower", "yhat_upper"} & columns else 0.85 if matched else 0.0
        return DetectionResult(
            matched,
            confidence,
            "Prophet-like dataframe with ds and yhat" if matched else "missing ds/yhat columns",
        )

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        schema = ForecastSchema(
            target_time="ds",
            prediction="yhat",
            lower="yhat_lower" if "yhat_lower" in obj else None,
            upper="yhat_upper" if "yhat_upper" in obj else None,
        )
        if context.model_name is None:
            context.model_name = "prophet"
        return normalize_dataframe(obj, context=context, adapter_name=self.name, schema=schema)

