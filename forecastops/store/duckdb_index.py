from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

from forecastops.core.run import ArtifactRecord, ForecastRun, MetricRecord, ValidationEvent, utc_now
from forecastops.store.local import LocalStore


class DuckDBIndex:
    def __init__(self, store: LocalStore):
        self.store = store
        self.store.init()
        self.path = self.store.db_path

    def connect(self) -> duckdb.DuckDBPyConnection:
        conn = duckdb.connect(str(self.path))
        conn.execute("SET timezone='UTC'")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)

    def upsert_project(self, project: str, metadata: dict[str, Any] | None = None) -> None:
        self.init()
        with self.connect() as conn:
            conn.execute(
                """
                insert into projects (project_id, name, created_at, metadata_json)
                values (?, ?, ?, ?)
                on conflict (project_id) do update set
                  name = excluded.name,
                  metadata_json = excluded.metadata_json
                """,
                [project, project, utc_now(), _json(metadata or {})],
            )

    def insert_run(
        self,
        *,
        run: ForecastRun,
        summary: dict[str, Any],
    ) -> None:
        self.init()
        with self.connect() as conn:
            conn.execute(
                """
                insert or replace into runs (
                  run_id, project_id, run_name, run_kind, status, created_at,
                  started_at, ended_at, model_name, model_version, adapter_name,
                  cutoff_start, cutoff_end, target_start, target_end, horizon_min,
                  horizon_max, series_count, points_count, forecast_artifact_uri,
                  actuals_artifact_uri, benchmark_artifact_uri, report_uri, trace_id,
                  metadata_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run.run_id,
                    run.project,
                    summary.get("run_name"),
                    summary.get("run_kind", "forecast"),
                    run.status,
                    summary.get("created_at", utc_now()),
                    summary.get("started_at"),
                    summary.get("ended_at"),
                    run.model_name,
                    run.model_version,
                    run.adapter_name,
                    summary.get("cutoff_start"),
                    summary.get("cutoff_end"),
                    summary.get("target_start"),
                    summary.get("target_end"),
                    str(summary.get("horizon_min")) if summary.get("horizon_min") is not None else None,
                    str(summary.get("horizon_max")) if summary.get("horizon_max") is not None else None,
                    summary.get("series_count"),
                    summary.get("points_count"),
                    run.forecast_artifact_uri,
                    run.actuals_artifact_uri,
                    run.benchmark_artifact_uri,
                    run.report_uri,
                    run.trace_id,
                    _json(run.metadata),
                ],
            )

    def insert_artifacts(self, artifacts: list[ArtifactRecord]) -> None:
        if not artifacts:
            return
        self.init()
        rows = [
            [
                artifact.artifact_id,
                artifact.run_id,
                artifact.artifact_type,
                artifact.uri,
                artifact.content_type,
                artifact.row_count,
                artifact.byte_size,
                _json(artifact.schema),
                artifact.sha256,
                artifact.created_at,
            ]
            for artifact in artifacts
        ]
        with self.connect() as conn:
            conn.executemany(
                """
                insert or replace into artifacts (
                  artifact_id, run_id, artifact_type, uri, content_type, row_count,
                  byte_size, schema_json, sha256, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def insert_validation_events(self, run_id: str, events: list[ValidationEvent]) -> None:
        self.init()
        with self.connect() as conn:
            conn.execute("delete from validation_events where run_id = ?", [run_id])
            if not events:
                return
            rows = [
                [
                    event.event_id or f"{run_id}:validation:{idx}",
                    run_id,
                    event.severity,
                    event.code,
                    event.message,
                    event.affected_column,
                    event.affected_count,
                    _json(event.sample or {}),
                    utc_now(),
                ]
                for idx, event in enumerate(events)
            ]
            conn.executemany(
                """
                insert into validation_events (
                  event_id, run_id, severity, code, message, affected_column,
                  affected_count, sample_json, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def insert_metrics(self, metrics: list[MetricRecord]) -> None:
        if not metrics:
            return
        self.init()
        with self.connect() as conn:
            conn.execute("delete from evaluation_metrics where run_id = ?", [metrics[0].run_id])
            rows = [
                [
                    metric.metric_id,
                    metric.run_id,
                    metric.metric_name,
                    metric.metric_value,
                    metric.benchmark_name,
                    metric.horizon_bucket,
                    metric.slice_name,
                    metric.slice_value,
                    metric.series_group,
                    metric.points_count,
                    metric.created_at or utc_now(),
                ]
                for metric in metrics
            ]
            conn.executemany(
                """
                insert into evaluation_metrics (
                  metric_id, run_id, metric_name, metric_value, benchmark_name,
                  horizon_bucket, slice_name, slice_value, series_group, points_count, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def insert_span(self, span: dict[str, Any]) -> None:
        self.init()
        with self.connect() as conn:
            conn.execute(
                """
                insert or replace into spans (
                  span_id, trace_id, run_id, parent_span_id, span_name, started_at,
                  ended_at, duration_ms, status, attributes_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    span["span_id"],
                    span["trace_id"],
                    span.get("run_id"),
                    span.get("parent_span_id"),
                    span["span_name"],
                    span["started_at"],
                    span.get("ended_at"),
                    span.get("duration_ms"),
                    span.get("status"),
                    _json(span.get("attributes", {})),
                ],
            )

    def latest_run_id(self) -> str | None:
        self.init()
        with self.connect() as conn:
            result = conn.execute(
                "select run_id from runs order by created_at desc limit 1"
            ).fetchone()
        return result[0] if result else None

    def run_by_id(self, run_id: str) -> dict[str, Any] | None:
        self.init()
        with self.connect() as conn:
            result = conn.execute("select * from runs where run_id = ?", [run_id]).fetchdf()
        if result.empty:
            return None
        return result.iloc[0].to_dict()


def summarize_frame(frame) -> dict[str, Any]:
    return {
        "created_at": utc_now(),
        "cutoff_start": frame["cutoff_time"].min(),
        "cutoff_end": frame["cutoff_time"].max(),
        "target_start": frame["target_time"].min(),
        "target_end": frame["target_time"].max(),
        "horizon_min": frame["horizon"].min() if "horizon" in frame else None,
        "horizon_max": frame["horizon"].max() if "horizon" in frame else None,
        "series_count": int(frame["series_id"].nunique()),
        "points_count": len(frame),
    }


def ensure_store(path: str | Path | None = None) -> DuckDBIndex:
    store = LocalStore.from_path(path)
    index = DuckDBIndex(store)
    index.init()
    return index


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)


SCHEMA_STATEMENTS = [
    """
    create table if not exists projects (
      project_id varchar primary key,
      name varchar not null,
      created_at timestamp not null,
      metadata_json json
    )
    """,
    """
    create table if not exists runs (
      run_id varchar primary key,
      project_id varchar not null,
      run_name varchar,
      run_kind varchar,
      status varchar,
      created_at timestamp not null,
      started_at timestamp,
      ended_at timestamp,
      model_name varchar,
      model_version varchar,
      adapter_name varchar,
      cutoff_start timestamp,
      cutoff_end timestamp,
      target_start timestamp,
      target_end timestamp,
      horizon_min varchar,
      horizon_max varchar,
      series_count bigint,
      points_count bigint,
      forecast_artifact_uri varchar,
      actuals_artifact_uri varchar,
      benchmark_artifact_uri varchar,
      report_uri varchar,
      trace_id varchar,
      metadata_json json
    )
    """,
    """
    create table if not exists evaluation_metrics (
      metric_id varchar primary key,
      run_id varchar not null,
      metric_name varchar not null,
      metric_value double not null,
      benchmark_name varchar,
      horizon_bucket varchar,
      slice_name varchar,
      slice_value varchar,
      series_group varchar,
      points_count bigint,
      created_at timestamp not null
    )
    """,
    """
    create table if not exists validation_events (
      event_id varchar primary key,
      run_id varchar not null,
      severity varchar not null,
      code varchar not null,
      message varchar not null,
      affected_column varchar,
      affected_count bigint,
      sample_json json,
      created_at timestamp not null
    )
    """,
    """
    create table if not exists artifacts (
      artifact_id varchar primary key,
      run_id varchar not null,
      artifact_type varchar not null,
      uri varchar not null,
      content_type varchar,
      row_count bigint,
      byte_size bigint,
      schema_json json,
      sha256 varchar,
      created_at timestamp not null
    )
    """,
    """
    create table if not exists spans (
      span_id varchar primary key,
      trace_id varchar not null,
      run_id varchar,
      parent_span_id varchar,
      span_name varchar not null,
      started_at timestamp not null,
      ended_at timestamp,
      duration_ms double,
      status varchar,
      attributes_json json
    )
    """,
]

