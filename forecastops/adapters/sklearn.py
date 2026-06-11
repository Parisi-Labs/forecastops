from __future__ import annotations

from typing import Any

from forecastops.adapters.dataframe import ArrayAdapter
from forecastops.core.run import CaptureContext, DetectionResult, NormalizedForecast


class SklearnArrayAdapter(ArrayAdapter):
    name = "sklearn"

    def detect(self, obj: Any) -> DetectionResult:
        result = super().detect(obj)
        if not result.matched:
            return result
        return DetectionResult(
            True,
            0.2,
            "array-like model predictions; explicit target_time and cutoff context required",
            ["target_time", "cutoff"],
        )

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        context.model_name = context.model_name or "sklearn"
        normalized = super().normalize(obj, context=context)
        normalized.adapter_name = self.name
        return normalized

