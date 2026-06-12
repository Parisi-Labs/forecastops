from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from forecastops.store.duckdb_index import DuckDBIndex, ensure_store

# Horizon buckets in chronological order, for stable "worst horizon" output.
_HORIZON_ORDER = ["0-1h", "1-6h", "6-24h", "24-48h", "48h-7d", "7d+", "unknown"]


def diagnose(
    run_id: str,
    *,
    store: str | Path | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Return a compact, machine-readable diagnosis of a captured run.

    Built entirely from the local index (plus one bounded per-series aggregate over
    the forecast artifact), this is the agent-facing summary: overall metrics, skill
    vs. benchmark, the worst horizons / series / regimes, validation state, and
    artifact URIs — everything an agent needs to decide what to try next, without
    reverse-engineering the DuckDB tables or pulling thousands of rows.
    """
    index = ensure_store(store)
    run = index.run_by_id(run_id)
    if run is None:
        raise ValueError(f"Run {run_id!r} not found in store {index.store.root}")

    metrics = _query(
        index,
        "select metric_name, metric_value, benchmark_name, slice_name, slice_value, points_count "
        "from evaluation_metrics where run_id = ?",
        run_id,
    )
    validation = _query(
        index,
        "select severity, code, message, affected_column, affected_count "
        "from validation_events where run_id = ?",
        run_id,
    )
    artifacts = _query(
        index,
        "select artifact_type, uri from artifacts where run_id = ?",
        run_id,
    )

    overall = {
        row["metric_name"]: row["metric_value"]
        for row in metrics
        if row["slice_name"] is None and row["benchmark_name"] is None
    }
    skill = {
        row["metric_name"]: row["metric_value"]
        for row in metrics
        if row["metric_name"].startswith("skill_") and row["slice_name"] is None
    }

    return {
        "run_id": run_id,
        "project": run.get("project_id"),
        "group": run.get("group_name"),
        "group_id": run.get("group_id"),
        "model": run.get("model_name"),
        "model_version": run.get("model_version"),
        "adapter": run.get("adapter_name"),
        "status": run.get("status"),
        "created_at": _iso(run.get("created_at")),
        "data": {
            "cutoff_start": _iso(run.get("cutoff_start")),
            "cutoff_end": _iso(run.get("cutoff_end")),
            "target_start": _iso(run.get("target_start")),
            "target_end": _iso(run.get("target_end")),
            "horizon_min": run.get("horizon_min"),
            "horizon_max": run.get("horizon_max"),
            "series_count": _int(run.get("series_count")),
            "points_count": _int(run.get("points_count")),
        },
        "overall": overall,
        "skill": skill,
        "worst_horizons": _worst_horizons(metrics, top_k),
        "worst_series": _worst_series(run.get("forecast_artifact_uri"), top_k),
        "worst_regimes": _worst_regimes(metrics, top_k),
        "validation": _validation_summary(validation),
        "artifacts": {row["artifact_type"]: row["uri"] for row in artifacts},
    }


def _worst_horizons(metrics: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    rows = [
        {"horizon_bucket": m["slice_value"], "wape": m["metric_value"], "points": _int(m["points_count"])}
        for m in metrics
        if m["slice_name"] == "horizon_bucket"
        and m["metric_name"] == "wape"
        and m["benchmark_name"] is None
    ]
    rows.sort(key=lambda r: r["wape"], reverse=True)
    return rows[:top_k]


def _worst_regimes(metrics: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    rows = [
        {
            "slice": m["slice_name"],
            "value": m["slice_value"],
            "wape": m["metric_value"],
            "points": _int(m["points_count"]),
        }
        for m in metrics
        if m["slice_name"] not in (None, "horizon_bucket", "series_group")
        and m["metric_name"] == "wape"
        and m["benchmark_name"] is None
    ]
    rows.sort(key=lambda r: r["wape"], reverse=True)
    return rows[:top_k]


def _worst_series(artifact_uri: str | None, top_k: int) -> list[dict[str, Any]]:
    """Per-series WAPE/MAE, aggregated server-side over the full forecast artifact."""
    if not artifact_uri or not Path(artifact_uri).exists():
        return []
    query = """
    select
      series_id,
      sum(abs(try_cast(yhat as double) - try_cast(actual as double))) as abs_error,
      sum(abs(try_cast(actual as double))) as abs_actual,
      count(*) filter (where actual is not null) as n
    from read_parquet(?)
    where actual is not null
    group by series_id
    having n > 0
    """
    with duckdb.connect(database=":memory:") as conn:
        conn.execute("SET timezone='UTC'")
        frame = conn.execute(query, [str(artifact_uri)]).fetchdf()
    if frame.empty:
        return []
    frame["wape"] = frame["abs_error"] / frame["abs_actual"].where(frame["abs_actual"] != 0)
    frame["mae"] = frame["abs_error"] / frame["n"]
    frame = frame.dropna(subset=["wape"]).sort_values("wape", ascending=False).head(top_k)
    return [
        {
            "series_id": str(row.series_id),
            "wape": float(row.wape),
            "mae": float(row.mae),
            "points": int(row.n),
        }
        for row in frame.itertuples()
    ]


def _validation_summary(validation: list[dict[str, Any]]) -> dict[str, Any]:
    def items(severity: str) -> list[dict[str, Any]]:
        return [
            {"code": row["code"], "message": row["message"], "column": row["affected_column"]}
            for row in validation
            if row["severity"] == severity
        ]

    errors = items("ERROR")
    warnings = items("WARN")
    status = "FAIL" if errors else "WARN" if warnings else "PASS"
    return {"status": status, "errors": errors, "warnings": warnings}


def _query(index: DuckDBIndex, sql: str, *params: Any) -> list[dict[str, Any]]:
    with index.connect(read_only=True) as conn:
        frame = conn.execute(sql, list(params)).fetchdf()
    return frame.to_dict(orient="records") if not frame.empty else []


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
