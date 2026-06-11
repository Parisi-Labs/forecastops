from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from forecastops.core.config import load_config
from forecastops.ui.queries import UIQueries

STATIC_DIR = Path(__file__).parent / "static"


def create_app(*, store: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="ForecastOps Local UI", version="0.1.0")
    queries = UIQueries(store)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return queries.health()

    @app.get("/api/projects")
    def projects() -> list[dict[str, Any]]:
        return queries.projects()

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return queries.runs()

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> dict[str, Any]:
        result = queries.run(run_id)
        if not result:
            raise HTTPException(status_code=404, detail="run not found")
        return result

    @app.get("/api/runs/{run_id}/metrics")
    def metrics(run_id: str) -> list[dict[str, Any]]:
        return queries.metrics(run_id)

    @app.get("/api/runs/{run_id}/validation")
    def validation(run_id: str) -> list[dict[str, Any]]:
        return queries.validation(run_id)

    @app.get("/api/runs/{run_id}/forecast-points")
    def forecast_points(
        run_id: str,
        series_id: str | None = None,
        limit: int = Query(2000, ge=1, le=10000),
    ) -> list[dict[str, Any]]:
        return queries.forecast_points(run_id, series_id=series_id, limit=limit)

    @app.get("/api/runs/{run_id}/residuals")
    def residuals(
        run_id: str,
        series_id: str | None = None,
        horizon_bucket: str | None = None,
        limit: int = Query(1000, ge=1, le=10000),
    ) -> list[dict[str, Any]]:
        return queries.residuals(
            run_id,
            series_id=series_id,
            horizon_bucket=horizon_bucket,
            limit=limit,
        )

    @app.get("/api/diff")
    def diff(base_run_id: str, candidate_run_id: str) -> dict[str, Any]:
        return queries.diff(base_run_id, candidate_run_id)

    @app.get("/api/artifacts/{artifact_id:path}/schema")
    def artifact_schema(artifact_id: str) -> dict[str, Any]:
        schema = queries.artifact_schema(artifact_id)
        if schema is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return schema

    return app


def ui(
    *,
    host: str | None = None,
    port: int | None = None,
    store: str | Path | None = None,
    open_browser: bool = True,
) -> None:
    config = load_config()
    resolved_host = host or config.ui_host
    resolved_port = port or config.ui_port
    if resolved_host == "0.0.0.0":
        print("Warning: ForecastOps UI is binding to 0.0.0.0. Local-only mode uses 127.0.0.1.")
    url = f"http://{resolved_host}:{resolved_port}"
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(store=store or config.store), host=resolved_host, port=resolved_port)

