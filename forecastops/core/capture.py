from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from forecastops.adapters.registry import adapter as adapter_decorator
from forecastops.adapters.registry import resolve_adapter
from forecastops.core.compare import attach_benchmark, compare
from forecastops.core.config import load_config
from forecastops.core.evaluate import (
    _normalize_actuals,
    attach_actuals,
    evaluate,
    resolve_default_series_id,
)
from forecastops.core.run import CaptureContext, ForecastRun, make_run_id, utc_now
from forecastops.core.schema import ForecastSchema
from forecastops.core.validate import validate_forecast, validation_status
from forecastops.otel import semconv
from forecastops.otel.metrics import ForecastMetricEmitter
from forecastops.otel.trace import ForecastTrace
from forecastops.store.duckdb_index import DuckDBIndex, summarize_frame
from forecastops.store.local import LocalStore
from forecastops.store.manifest import write_run_manifest
from forecastops.store.parquet import write_dataframe_artifact

adapter = adapter_decorator


def capture(
    obj: Any,
    *,
    project: str = "default",
    adapter: str | None = None,
    schema: ForecastSchema | dict[str, Any] | None = None,
    series_id: Any | None = None,
    cutoff: Any | None = None,
    target_time: Any | None = None,
    actuals: pd.DataFrame | None = None,
    benchmark: pd.DataFrame | None = None,
    benchmark_name: str = "benchmark",
    model_name: str | None = None,
    model_version: str | None = None,
    metadata: dict[str, Any] | None = None,
    run_id: str | None = None,
    run_name: str | None = None,
    run_kind: str = "forecast",
    store: str | Path | None = None,
    allow_insample: bool | None = None,
    strict: bool = False,
    **adapter_options: Any,
) -> ForecastRun:
    config = load_config()
    schema_obj = schema if isinstance(schema, ForecastSchema) else ForecastSchema.from_dict(schema)
    resolved_store = LocalStore.from_path(store or config.store)
    resolved_store.init()
    index = DuckDBIndex(resolved_store)
    index.init()

    run_id = run_id or make_run_id(project, model_name)
    context = CaptureContext(
        project=project,
        run_id=run_id,
        series_id=series_id,
        cutoff=cutoff,
        target_time=target_time,
        model_name=model_name,
        model_version=model_version,
        schema=schema_obj,
        adapter_options=adapter_options,
        metadata=metadata or {},
        run_name=run_name,
        run_kind=run_kind,
        store_path=resolved_store.root,
        allow_insample=config.allow_insample if allow_insample is None else allow_insample,
    )

    trace = ForecastTrace(index=index, run_id=run_id)
    started_at = utc_now()
    artifacts = []
    with trace.span(
        semconv.SPAN_FORECAST_RUN,
        attributes={
            semconv.FORECAST_PROJECT_NAME: project,
            semconv.FORECAST_RUN_ID: run_id,
            semconv.FORECAST_RUN_KIND: run_kind,
        },
    ) as root_span_id:
        with trace.span(semconv.SPAN_ADAPTER_DETECT, parent_span_id=root_span_id):
            adapter_impl = resolve_adapter(obj, adapter, context)
        with trace.span(semconv.SPAN_OUTPUT_NORMALIZE, parent_span_id=root_span_id):
            normalized = adapter_impl.normalize(obj, context=context)
            frame = normalized.frame
            actuals_series_id = resolve_default_series_id(frame)
            if actuals is not None:
                frame = attach_actuals(frame, actuals)
            if benchmark is not None:
                frame = attach_benchmark(frame, benchmark, benchmark_name=benchmark_name)
        with trace.span(semconv.SPAN_OUTPUT_VALIDATE, parent_span_id=root_span_id):
            events = validate_forecast(
                frame,
                allow_insample=context.allow_insample,
                max_slice_cardinality=config.max_slice_cardinality,
            )
            if strict and any(event.is_error for event in events):
                messages = "; ".join(f"{event.code}: {event.message}" for event in events if event.is_error)
                raise ValueError(messages)

        with trace.span(semconv.SPAN_ARTIFACT_WRITE, parent_span_id=root_span_id):
            forecast_artifact = write_dataframe_artifact(
                frame,
                store=resolved_store,
                run_id=run_id,
                artifact_type="forecast",
            )
            artifacts.append(forecast_artifact)
            actuals_artifact_uri = None
            benchmark_artifact_uri = None
            if actuals is not None:
                actuals_artifact = write_dataframe_artifact(
                    _normalize_actuals(actuals, default_series_id=actuals_series_id),
                    store=resolved_store,
                    run_id=run_id,
                    artifact_type="actuals",
                )
                artifacts.append(actuals_artifact)
                actuals_artifact_uri = actuals_artifact.uri
            if benchmark is not None:
                benchmark_artifact = write_dataframe_artifact(
                    attach_benchmark(
                        frame[
                            [
                                column
                                for column in ["series_id", "cutoff_time", "target_time"]
                                if column in frame
                            ]
                        ],
                        benchmark,
                        benchmark_name=benchmark_name,
                    ),
                    store=resolved_store,
                    run_id=run_id,
                    artifact_type="benchmark",
                )
                artifacts.append(benchmark_artifact)
                benchmark_artifact_uri = benchmark_artifact.uri

        metric_records = []
        if "actual" in frame and frame["actual"].notna().any():
            has_benchmark = "benchmark_yhat" in frame and frame["benchmark_yhat"].notna().any()
            if has_benchmark:
                # compare() computes the full model-side metric set (including count), so
                # the standalone evaluate() pass would be redundant work.
                with trace.span(semconv.SPAN_BENCHMARK_COMPARE, parent_span_id=root_span_id):
                    metric_records = compare(
                        frame,
                        benchmark_name=benchmark_name,
                        run_id=run_id,
                        max_slice_cardinality=config.max_slice_cardinality,
                    ).metrics
            else:
                with trace.span(semconv.SPAN_EVALUATE, parent_span_id=root_span_id):
                    metric_records = evaluate(
                        frame,
                        run_id=run_id,
                        max_slice_cardinality=config.max_slice_cardinality,
                    ).metrics

    model_name_resolved = str(frame["model_name"].dropna().iloc[0]) if "model_name" in frame else "unknown"
    model_version_values = frame["model_version"].dropna() if "model_version" in frame else pd.Series([])
    model_version_resolved = str(model_version_values.iloc[0]) if not model_version_values.empty else model_version
    run = ForecastRun(
        run_id=run_id,
        project=project,
        model_name=model_name_resolved,
        model_version=model_version_resolved,
        adapter_name=normalized.adapter_name,
        store_path=resolved_store.root,
        forecast_artifact_uri=forecast_artifact.uri,
        actuals_artifact_uri=actuals_artifact_uri,
        benchmark_artifact_uri=benchmark_artifact_uri,
        trace_id=trace.trace_id,
        validation_events=events,
        metrics=metric_records,
        metadata={
            **(metadata or {}),
            "validation_status": validation_status(events),
            "adapter_options": adapter_options,
        },
        raw_output=obj,
    )
    summary = summarize_frame(frame)
    summary.update(
        {
            "run_name": run_name,
            "run_kind": run_kind,
            "started_at": started_at,
            "ended_at": utc_now(),
        }
    )
    index.upsert_project(project, metadata)
    index.insert_artifacts(artifacts)
    index.insert_validation_events(run_id, events)
    index.insert_metrics(metric_records)
    if config.otel_enabled and metric_records:
        ForecastMetricEmitter().emit(
            metric_records,
            base_attributes={
                semconv.FORECAST_PROJECT_NAME: project,
                semconv.FORECAST_MODEL_NAME: run.model_name,
                semconv.FORECAST_MODEL_VERSION: run.model_version,
                semconv.FORECAST_RUN_KIND: run_kind,
                semconv.FORECAST_ADAPTER_NAME: run.adapter_name,
            },
        )
    index.insert_run(run=run, summary=summary)
    write_run_manifest(run)
    return run
