from __future__ import annotations

from typing import Any

import pandas as pd

from forecastops.adapters.base import ForecastAdapter
from forecastops.core.normalize import normalize_array, normalize_dataframe
from forecastops.core.run import CaptureContext, DetectionResult, NormalizedForecast
from forecastops.core.schema import ForecastSchema


class GenericDataFrameAdapter(ForecastAdapter):
    name = "dataframe"

    def detect(self, obj: Any) -> DetectionResult:
        if not isinstance(obj, pd.DataFrame):
            return DetectionResult(False, 0.0, "object is not a pandas DataFrame")
        has_target = any(column in obj.columns for column in ["target_time", "ds", "timestamp"])
        has_prediction = any(column in obj.columns for column in ["yhat", "prediction", "forecast"])
        matched = has_target and has_prediction
        return DetectionResult(
            matched,
            0.55 if matched else 0.0,
            "generic dataframe columns found" if matched else "missing target or prediction column",
            [] if matched else ["target_time", "prediction"],
        )

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        return normalize_dataframe(obj, context=context, adapter_name=self.name)


class SchemaDataFrameAdapter(ForecastAdapter):
    name = "schema"

    def detect(self, obj: Any) -> DetectionResult:
        matched = isinstance(obj, pd.DataFrame)
        return DetectionResult(matched, 0.8 if matched else 0.0, "schema mapping supplied")

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        schema = context.schema
        if not isinstance(schema, ForecastSchema):
            raise ValueError("schema adapter requires ForecastSchema")
        return normalize_dataframe(obj, context=context, adapter_name=self.name, schema=schema)


class ArrayAdapter(ForecastAdapter):
    name = "array"

    def detect(self, obj: Any) -> DetectionResult:
        if isinstance(obj, pd.DataFrame):
            return DetectionResult(False, 0.0, "dataframe should use dataframe adapters")
        if hasattr(obj, "__array__") or isinstance(obj, (list, tuple)):
            return DetectionResult(
                True,
                0.25,
                "array-like object; requires explicit target_time and cutoff context",
                ["target_time", "cutoff"],
            )
        return DetectionResult(False, 0.0, "object is not array-like")

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        return normalize_array(obj, context=context)

