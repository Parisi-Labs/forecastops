from __future__ import annotations

from typing import Any

import pandas as pd

from forecastops.adapters.base import ForecastAdapter
from forecastops.core.normalize import normalize_dataframe
from forecastops.core.run import CaptureContext, DetectionResult, NormalizedForecast
from forecastops.core.schema import ForecastSchema

RESERVED_COLUMNS = {"unique_id", "ds", "cutoff", "cutoff_time", "actual", "y"}


class NixtlaAdapter(ForecastAdapter):
    name = "nixtla"

    def detect(self, obj: Any) -> DetectionResult:
        if not isinstance(obj, pd.DataFrame):
            return DetectionResult(False, 0.0, "object is not a pandas DataFrame")
        columns = set(obj.columns)
        model_cols = [column for column in obj.columns if column not in RESERVED_COLUMNS]
        matched = {"unique_id", "ds"}.issubset(columns) and bool(model_cols)
        return DetectionResult(
            matched,
            0.9 if matched else 0.0,
            "Nixtla-style dataframe with unique_id, ds, and model columns"
            if matched
            else "missing unique_id/ds/model columns",
            [] if matched else ["unique_id", "ds", "model_col"],
        )

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        model_col = context.adapter_options.get("model_col")
        if model_col is None:
            candidates = [column for column in obj.columns if column not in RESERVED_COLUMNS]
            if not candidates:
                raise ValueError("nixtla adapter requires at least one model output column")
            model_col = candidates[0]
        if model_col not in obj:
            raise ValueError(f"model_col {model_col!r} not present in dataframe")
        schema = ForecastSchema(
            series_id="unique_id",
            cutoff_time="cutoff_time" if "cutoff_time" in obj else None,
            target_time="ds",
            prediction=model_col,
            actual="actual" if "actual" in obj else "y" if "y" in obj else None,
        )
        context.model_name = context.model_name or str(model_col)
        return normalize_dataframe(obj, context=context, adapter_name=self.name, schema=schema)

