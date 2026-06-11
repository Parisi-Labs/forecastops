from __future__ import annotations

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from opentelemetry import trace as otel_trace

from forecastops.core.run import utc_now
from forecastops.store.duckdb_index import DuckDBIndex


@dataclass(slots=True)
class ForecastTrace:
    index: DuckDBIndex
    run_id: str
    trace_id: str = field(default_factory=lambda: secrets.token_hex(16))
    enabled: bool = field(default_factory=lambda: os.environ.get("FOPS_OTEL_ENABLED", "").lower() == "true")

    @contextmanager
    def span(
        self,
        span_name: str,
        *,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        span_id = secrets.token_hex(8)
        started_at = utc_now()
        status = "ok"
        otel_cm = None
        otel_span = None
        if self.enabled:
            tracer = otel_trace.get_tracer("forecastops")
            otel_cm = tracer.start_as_current_span(span_name)
            otel_span = otel_cm.__enter__()
            for key, value in (attributes or {}).items():
                if value is not None:
                    otel_span.set_attribute(key, str(value))
        try:
            yield span_id
        except Exception:
            status = "error"
            if otel_span is not None:
                otel_span.set_status(otel_trace.Status(otel_trace.StatusCode.ERROR))
            raise
        finally:
            ended_at = utc_now()
            self.index.insert_span(
                {
                    "span_id": span_id,
                    "trace_id": self.trace_id,
                    "run_id": self.run_id,
                    "parent_span_id": parent_span_id,
                    "span_name": span_name,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "duration_ms": _duration_ms(started_at, ended_at),
                    "status": status,
                    "attributes": attributes or {},
                }
            )
            if otel_cm is not None:
                otel_cm.__exit__(None, None, None)


def _duration_ms(started_at: datetime, ended_at: datetime) -> float:
    return (ended_at - started_at).total_seconds() * 1000

