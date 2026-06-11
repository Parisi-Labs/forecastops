from __future__ import annotations

from typing import Any

from forecastops.adapters.base import ForecastAdapter
from forecastops.adapters.dataframe import ArrayAdapter, GenericDataFrameAdapter, SchemaDataFrameAdapter
from forecastops.adapters.darts import DartsAdapter
from forecastops.adapters.gluonts import GluonTSAdapter
from forecastops.adapters.nixtla import NixtlaAdapter
from forecastops.adapters.prophet import ProphetAdapter
from forecastops.adapters.sklearn import SklearnArrayAdapter
from forecastops.core.run import CaptureContext

_CUSTOM_ADAPTERS: dict[str, ForecastAdapter] = {}


def adapter(name: str):
    def decorator(cls: type[ForecastAdapter]) -> type[ForecastAdapter]:
        _CUSTOM_ADAPTERS[name] = cls()
        return cls

    return decorator


def builtin_adapters() -> list[ForecastAdapter]:
    return [
        DartsAdapter(),
        GluonTSAdapter(),
        ProphetAdapter(),
        NixtlaAdapter(),
        GenericDataFrameAdapter(),
        SklearnArrayAdapter(),
        ArrayAdapter(),
    ]


def resolve_adapter(obj: Any, adapter_name: str | None, context: CaptureContext) -> ForecastAdapter:
    if adapter_name:
        if adapter_name == "schema":
            return SchemaDataFrameAdapter()
        adapters = {adapter.name: adapter for adapter in [*_CUSTOM_ADAPTERS.values(), *builtin_adapters()]}
        if adapter_name not in adapters:
            raise ValueError(f"Unknown adapter {adapter_name!r}")
        return adapters[adapter_name]
    if context.schema is not None:
        return SchemaDataFrameAdapter()

    candidates: list[tuple[float, ForecastAdapter]] = []
    for candidate in [*_CUSTOM_ADAPTERS.values(), *builtin_adapters()]:
        result = candidate.detect(obj)
        if result.matched:
            candidates.append((result.confidence, candidate))
    if not candidates:
        raise ValueError("Could not detect a ForecastOps adapter. Supply adapter= or schema= explicitly.")
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]
