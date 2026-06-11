from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from forecastops.core.diff import diff as diff_runs
from forecastops.store.duckdb_index import DuckDBIndex
from forecastops.store.local import LocalStore
from forecastops.store.parquet import read_artifact


class UIQueries:
    def __init__(self, store_path: str | Path | None = None):
        self.store = LocalStore.from_path(store_path)
        self.index = DuckDBIndex(self.store)
        self.index.init()

    def projects(self) -> list[dict[str, Any]]:
        return _records(self._query("select * from projects order by created_at desc"))

    def runs(self) -> list[dict[str, Any]]:
        query = """
        select
          r.*,
          max(case when m.metric_name = 'mae' and m.slice_name is null then m.metric_value end) as mae,
          max(case when m.metric_name = 'wape' and m.slice_name is null then m.metric_value end) as wape,
          max(case when m.metric_name = 'bias' and m.slice_name is null then m.metric_value end) as bias,
          max(case when m.metric_name = 'coverage' and m.slice_name is null then m.metric_value end) as coverage,
          max(case when starts_with(m.metric_name, 'skill_') and m.slice_name is null then m.metric_value end)
            as skill_vs_benchmark,
          case
            when sum(case when v.severity = 'ERROR' then 1 else 0 end) > 0 then 'FAIL'
            when sum(case when v.severity = 'WARN' then 1 else 0 end) > 0 then 'WARN'
            else 'PASS'
          end as validation_status
        from runs r
        left join evaluation_metrics m on r.run_id = m.run_id
        left join validation_events v on r.run_id = v.run_id
        group by all
        order by r.created_at desc
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
        frame = read_artifact(run["forecast_artifact_uri"])
        if series_id:
            frame = frame[frame["series_id"].astype(str) == str(series_id)]
        frame = frame.sort_values(["series_id", "target_time"]).head(max(1, min(limit, 10000)))
        return _records(frame)

    def residuals(
        self,
        run_id: str,
        *,
        series_id: str | None = None,
        horizon_bucket: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        points = pd.DataFrame(self.forecast_points(run_id, series_id=series_id, limit=10000))
        if points.empty or "actual" not in points:
            return []
        points["target_time"] = pd.to_datetime(points["target_time"], errors="coerce")
        points["cutoff_time"] = pd.to_datetime(points["cutoff_time"], errors="coerce")
        points["residual"] = pd.to_numeric(points["yhat"], errors="coerce") - pd.to_numeric(
            points["actual"], errors="coerce"
        )
        points["horizon_bucket"] = points.apply(_horizon_bucket, axis=1)
        if horizon_bucket:
            points = points[points["horizon_bucket"] == horizon_bucket]
        points = points.dropna(subset=["residual"]).sort_values("target_time").head(limit)
        return _records(points)

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
        with duckdb.connect(str(self.store.db_path), read_only=True) as conn:
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


def _horizon_bucket(row: pd.Series) -> str:
    duration = row["target_time"] - row["cutoff_time"]
    if pd.isna(duration):
        return "unknown"
    hours = duration.total_seconds() / 3600
    if hours <= 1:
        return "0-1h"
    if hours <= 6:
        return "1-6h"
    if hours <= 24:
        return "6-24h"
    if hours <= 48:
        return "24-48h"
    if hours <= 24 * 7:
        return "48h-7d"
    return "7d+"

