from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from forecastops.core.run import ForecastRun


def write_run_manifest(run: ForecastRun) -> Path:
    path = run.store_path / "artifacts" / "forecasts" / f"{run.run_id}.manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "run_id": run.run_id,
        "project": run.project,
        "model_name": run.model_name,
        "model_version": run.model_version,
        "adapter_name": run.adapter_name,
        "forecast_artifact_uri": run.forecast_artifact_uri,
        "actuals_artifact_uri": run.actuals_artifact_uri,
        "benchmark_artifact_uri": run.benchmark_artifact_uri,
        "report_uri": run.report_uri,
        "trace_id": run.trace_id,
        "status": run.status,
        "metadata": run.metadata,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path

