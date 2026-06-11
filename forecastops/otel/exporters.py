from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class InMemoryForecastExporter:
    spans: list[dict[str, Any]] = field(default_factory=list)
    metrics: list[tuple[str, float, dict[str, Any]]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def export_span(self, span: dict[str, Any]) -> None:
        self.spans.append(span)

    def export_metric(self, name: str, value: float, attributes: dict[str, Any]) -> None:
        self.metrics.append((name, value, attributes))

    def export_event(self, name: str, attributes: dict[str, Any]) -> None:
        self.events.append({"name": name, "attributes": attributes})

    def clear(self) -> None:
        self.spans.clear()
        self.metrics.clear()
        self.events.clear()

