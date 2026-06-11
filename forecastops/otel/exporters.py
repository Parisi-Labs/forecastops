"""Optional OpenTelemetry SDK wiring for forecastops telemetry.

ForecastOps records metrics through the global ``opentelemetry`` API; without
an SDK meter provider installed those calls are no-ops by design. Call
:func:`configure_console_export` (or install your own ``MeterProvider``) to
actually export — for example before running ``examples/otel_console.py``.
"""

from __future__ import annotations

from typing import Any

from forecastops.core.config import load_config


def configure_console_export(*, export_interval_millis: float = 5000) -> Any:
    """Install a global SDK ``MeterProvider`` that prints metrics to stdout.

    Requires the optional ``opentelemetry-sdk`` dependency
    (``pip install forecastops[otel]``). Returns the installed provider; call
    its ``shutdown()`` to flush pending metrics. Note the global OpenTelemetry
    meter provider can only be set once per process.
    """
    try:
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK extra
        raise RuntimeError(
            "opentelemetry-sdk is required for console export; "
            "install it with `pip install forecastops[otel]`."
        ) from exc

    from opentelemetry import metrics as otel_metrics

    reader = PeriodicExportingMetricReader(
        ConsoleMetricExporter(), export_interval_millis=export_interval_millis
    )
    provider = MeterProvider(
        metric_readers=[reader],
        resource=Resource.create({"service.name": load_config().otel_service_name}),
    )
    otel_metrics.set_meter_provider(provider)
    return provider
