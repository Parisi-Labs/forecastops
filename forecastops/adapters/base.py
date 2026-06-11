from __future__ import annotations

from typing import Any, Protocol

from forecastops.core.run import CaptureContext, DetectionResult, NormalizedForecast


class ForecastAdapter(Protocol):
    name: str

    def detect(self, obj: Any) -> DetectionResult:
        ...

    def normalize(self, obj: Any, *, context: CaptureContext) -> NormalizedForecast:
        ...

