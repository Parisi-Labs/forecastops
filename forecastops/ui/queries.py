from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from forecastops.core.diff import diff as diff_runs
from forecastops.store.duckdb_index import DuckDBIndex
from forecastops.store.local import LocalStore


class UIQueries:
    def __init__(self, store_path: str | Path | None = None):
        self.store = LocalStore.from_path(store_path)
        self.index = DuckDBIndex(self.store)
        self.index.init()

    def projects(self) -> list[dict[str, Any]]:
        return _records(self._query("select * from projects order by created_at desc"))

    def runs(self) -> list[dict[str, Any]]:
        query = """
        with metric_summary as (
          -- model-side aggregates only: benchmark rows share metric_name but
          -- carry benchmark_name, except skill_* which is inherently benchmarked
          select
            run_id,
            max(case when metric_name = 'mae' and slice_name is null and benchmark_name is null
              then metric_value end) as mae,
            max(case when metric_name = 'wape' and slice_name is null and benchmark_name is null
              then metric_value end) as wape,
            max(case when metric_name = 'bias' and slice_name is null and benchmark_name is null
              then metric_value end) as bias,
            max(case when metric_name = 'coverage' and slice_name is null and benchmark_name is null
              then metric_value end) as coverage,
            max(case when metric_name = 'coverage_gap' and slice_name is null and benchmark_name is null
              then metric_value end) as coverage_gap,
            min(case when starts_with(metric_name, 'skill_') and slice_name is null then metric_value end)
              as skill_vs_benchmark
          from evaluation_metrics
          group by run_id
        ),
        validation_summary as (
          select
            run_id,
            case
              when sum(case when severity = 'ERROR' then 1 else 0 end) > 0 then 'FAIL'
              when sum(case when severity = 'WARN' then 1 else 0 end) > 0 then 'WARN'
              else 'PASS'
            end as validation_status
          from validation_events
          group by run_id
        )
        select
          r.*,
          m.mae,
          m.wape,
          m.bias,
          m.coverage,
          m.coverage_gap,
          m.skill_vs_benchmark,
          coalesce(v.validation_status, 'PASS') as validation_status
        from runs r
        left join metric_summary m on r.run_id = m.run_id
        left join validation_summary v on r.run_id = v.run_id
        order by r.created_at desc
        """
        return _records(self._query(query))

    def groups(self) -> list[dict[str, Any]]:
        query = """
        with group_runs as (
          select
            g.group_id, g.name, g.kind, g.project_id, g.created_at,
            count(r.run_id) as run_count,
            max(r.created_at) as last_run_at
          from run_groups g
          left join runs r on r.group_id = g.group_id
          group by g.group_id, g.name, g.kind, g.project_id, g.created_at
        ),
        group_mae as (
          select r.group_id, avg(m.metric_value) as mean_mae
          from runs r
          join evaluation_metrics m
            on m.run_id = r.run_id
           and m.metric_name = 'mae'
           and m.slice_name is null
           and m.benchmark_name is null
          where r.group_id is not null
          group by r.group_id
        )
        select gr.*, gm.mean_mae
        from group_runs gr
        left join group_mae gm on gm.group_id = gr.group_id
        order by gr.last_run_at desc nulls last
        """
        return _records(self._query(query))

    def run(self, run_id: str) -> dict[str, Any] | None:
        rows = _records(self._query("select * from runs where run_id = ?", run_id))
        if not rows:
            return None
        run = rows[0]
        run["metrics"] = self.metrics(run_id)
        run["validation"] = self.validation(run_id)
        run["artifacts"] = self.artifacts(run_id)
        run["spans"] = self.spans(run_id)
        return run

    def metrics(self, run_id: str) -> list[dict[str, Any]]:
        return _records(
            self._query(
                """
                select *
                from evaluation_metrics
                where run_id = ?
                order by metric_name, slice_name, slice_value
                """,
                run_id,
            )
        )

    def validation(self, run_id: str) -> list[dict[str, Any]]:
        return _records(
            self._query(
                """
                select *
                from validation_events
                where run_id = ?
                order by case severity when 'ERROR' then 0 when 'WARN' then 1 else 2 end, code
                """,
                run_id,
            )
        )

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return _records(
            self._query("select * from artifacts where run_id = ? order by artifact_type", run_id)
        )

    def spans(self, run_id: str) -> list[dict[str, Any]]:
        return _records(
            self._query("select * from spans where run_id = ? order by started_at", run_id)
        )

    def forecast_points(
        self,
        run_id: str,
        *,
        series_id: str | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        run = self.index.run_by_id(run_id)
        if not run:
            return []
        query = "select * from read_parquet(?)"
        params: list[Any] = [str(run["forecast_artifact_uri"])]
        if series_id:
            query += " where cast(series_id as varchar) = ?"
            params.append(str(series_id))
        query += " order by series_id, target_time limit ?"
        params.append(max(1, min(limit, 10000)))
        with duckdb.connect() as conn:
            frame = conn.execute(query, params).fetchdf()
        return _records(frame)

    def residuals(
        self,
        run_id: str,
        *,
        series_id: str | None = None,
        horizon_bucket: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        run = self.index.run_by_id(run_id)
        if not run:
            return []
        uri = str(run["forecast_artifact_uri"])
        with duckdb.connect() as conn:
            columns = conn.execute(
                "select * from read_parquet(?) limit 0", [uri]
            ).fetchdf().columns
            if "actual" not in columns:
                return []
            series_filter = ""
            params: list[Any] = [uri]
            if series_id:
                series_filter = "where cast(series_id as varchar) = ?"
                params.append(str(series_id))
            query = f"""
            with points as (
              select
                *,
                try_cast(yhat as double) - try_cast(actual as double) as residual,
                date_diff(
                  'second',
                  try_cast(cutoff_time as timestamp),
                  try_cast(target_time as timestamp)
                ) / 3600.0 as _hours
              from read_parquet(?)
              {series_filter}
            ),
            bucketed as (
              select
                * exclude (_hours),
                case
                  when _hours is null then 'unknown'
                  when _hours <= 1 then '0-1h'
                  when _hours <= 6 then '1-6h'
                  when _hours <= 24 then '6-24h'
                  when _hours <= 48 then '24-48h'
                  when _hours <= 24 * 7 then '48h-7d'
                  else '7d+'
                end as horizon_bucket
              from points
            )
            select *
            from bucketed
            where residual is not null
            """
            if horizon_bucket:
                query += " and horizon_bucket = ?"
                params.append(horizon_bucket)
            query += " order by try_cast(target_time as timestamp) limit ?"
            params.append(max(1, limit))
            frame = conn.execute(query, params).fetchdf()
        return _records(frame)

    def diff(self, base_run_id: str, candidate_run_id: str) -> dict[str, Any]:
        base = self.index.run_by_id(base_run_id)
        candidate = self.index.run_by_id(candidate_run_id)
        if not base or not candidate:
            return {"metric_deltas": [], "forecast_deltas": [], "regressions": []}
        result = diff_runs(base["forecast_artifact_uri"], candidate["forecast_artifact_uri"])
        return {
            "base_run_id": result.base_run_id,
            "candidate_run_id": result.candidate_run_id,
            "metric_deltas": _records(result.metric_deltas),
            "forecast_deltas": _records(result.forecast_deltas.head(1000)),
            "regressions": _records(result.regressions),
        }

    def artifact_schema(self, artifact_id: str) -> dict[str, Any] | None:
        rows = _records(self._query("select * from artifacts where artifact_id = ?", artifact_id))
        if not rows:
            return None
        schema = rows[0].get("schema_json")
        if isinstance(schema, str):
            return json.loads(schema)
        return schema

    def health(self) -> dict[str, Any]:
        return {"ok": True, "store": str(self.store.root), "db": str(self.store.db_path)}

    def _query(self, query: str, *params: Any) -> pd.DataFrame:
        with self.index.connect(read_only=True) as conn:
            return conn.execute(query, params).fetchdf()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    clean = frame.copy()
    for column in clean.columns:
        clean[column] = clean[column].map(_json_safe)
    return clean.to_dict(orient="records")


def _json_safe(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value
