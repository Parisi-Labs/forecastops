from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import typer
import yaml

from forecastops.adapters.registry import resolve_adapter
from forecastops.core.capture import capture
from forecastops.core.compare import compare as compare_run
from forecastops.core.config import load_config, write_default_config
from forecastops.core.diff import diff as diff_runs
from forecastops.core.evaluate import evaluate as evaluate_run
from forecastops.core.report import report as generate_report
from forecastops.core.run import CaptureContext
from forecastops.core.schema import ForecastSchema
from forecastops.core.validate import validate_forecast
from forecastops.store.duckdb_index import DuckDBIndex
from forecastops.store.local import LocalStore
from forecastops.store.parquet import read_artifact
from forecastops.ui.server import ui as launch_ui

app = typer.Typer(help="ForecastOps local forecast observability.")


@app.command()
def init(
    store: Path = typer.Option(Path(".forecastops"), help="Local ForecastOps store path."),
    config: Path = typer.Option(Path("forecastops.yaml"), help="Config file path."),
) -> None:
    local_store = LocalStore.from_path(store)
    local_store.init()
    DuckDBIndex(local_store).init()
    write_default_config(config)
    typer.echo(f"Initialized {local_store.root}")


@app.command("capture")
def capture_file(
    forecast_path: Path = typer.Argument(..., help="Forecast dataframe file."),
    project: str = typer.Option("default", help="Project name."),
    schema: Path | None = typer.Option(None, help="YAML schema mapping."),
    adapter: str | None = typer.Option(None, help="Adapter name."),
    cutoff: str | None = typer.Option(None, help="Forecast cutoff time."),
    series_id: str | None = typer.Option(None, help="Single series id."),
    actuals: Path | None = typer.Option(None, help="Actuals dataframe file."),
    benchmark: Path | None = typer.Option(None, help="Benchmark dataframe file."),
    benchmark_name: str = typer.Option("benchmark", help="Benchmark name."),
    model_name: str | None = typer.Option(None, help="Model name."),
    store: Path | None = typer.Option(None, help="Local store path."),
) -> None:
    forecast = _read_frame(forecast_path)
    run = capture(
        forecast,
        project=project,
        schema=_read_schema(schema),
        adapter=adapter,
        cutoff=cutoff,
        series_id=series_id,
        actuals=_read_frame(actuals) if actuals else None,
        benchmark=_read_frame(benchmark) if benchmark else None,
        benchmark_name=benchmark_name,
        model_name=model_name,
        store=store,
    )
    typer.echo(json.dumps({"run_id": run.run_id, "status": run.status}, indent=2))


@app.command()
def lint(
    forecast_path: Path = typer.Argument(..., help="Forecast dataframe file."),
    schema: Path | None = typer.Option(None, help="YAML schema mapping."),
    adapter: str | None = typer.Option(None, help="Adapter name."),
    project: str = typer.Option("lint", help="Project context."),
    cutoff: str | None = typer.Option(None, help="Forecast cutoff time."),
    series_id: str | None = typer.Option(None, help="Single series id."),
    allow_insample: bool = typer.Option(False, help="Allow target_time <= cutoff_time."),
) -> None:
    frame = _read_frame(forecast_path)
    schema_obj = _read_schema(schema)
    context = CaptureContext(
        project=project,
        run_id="lint",
        cutoff=cutoff,
        series_id=series_id,
        schema=schema_obj,
        model_name="lint",
    )
    adapter_impl = resolve_adapter(frame, adapter, context)
    normalized = adapter_impl.normalize(frame, context=context).frame
    events = validate_forecast(normalized, allow_insample=allow_insample)
    for event in events:
        typer.echo(
            f"{event.severity:<5} {event.code}: {event.message}"
            + (f" ({event.affected_count})" if event.affected_count else "")
        )
    if any(event.is_error for event in events):
        raise typer.Exit(1)


@app.command()
def evaluate(
    run_id: str = typer.Argument(..., help="Run id."),
    actuals: Path | None = typer.Option(None, help="Actuals dataframe file."),
    store: Path | None = typer.Option(None, help="Local store path."),
) -> None:
    index = DuckDBIndex(LocalStore.from_path(store))
    run = index.run_by_id(run_id)
    if not run:
        raise typer.BadParameter(f"Run {run_id!r} not found")
    result = evaluate_run(
        read_artifact(run["forecast_artifact_uri"]),
        run_id=run_id,
        actuals=_read_frame(actuals) if actuals else None,
    )
    index.insert_metrics(result.metrics)
    typer.echo(result.to_frame().to_string(index=False))


@app.command()
def compare(
    run_id: str = typer.Argument(..., help="Run id."),
    benchmark: Path = typer.Option(..., help="Benchmark dataframe file."),
    benchmark_name: str = typer.Option("benchmark", help="Benchmark name."),
    store: Path | None = typer.Option(None, help="Local store path."),
) -> None:
    index = DuckDBIndex(LocalStore.from_path(store))
    run = index.run_by_id(run_id)
    if not run:
        raise typer.BadParameter(f"Run {run_id!r} not found")
    result = compare_run(
        read_artifact(run["forecast_artifact_uri"]),
        benchmark=_read_frame(benchmark),
        benchmark_name=benchmark_name,
    )
    index.insert_metrics(result.metrics)
    typer.echo(result.to_frame().to_string(index=False))


@app.command()
def diff(
    base_run_id: str = typer.Argument(..., help="Base run id."),
    candidate_run_id: str = typer.Argument(..., help="Candidate run id."),
    store: Path | None = typer.Option(None, help="Local store path."),
) -> None:
    index = DuckDBIndex(LocalStore.from_path(store))
    base = index.run_by_id(base_run_id)
    candidate = index.run_by_id(candidate_run_id)
    if not base or not candidate:
        raise typer.BadParameter("Both runs must exist")
    result = diff_runs(base["forecast_artifact_uri"], candidate["forecast_artifact_uri"])
    typer.echo(result.metric_deltas.to_string(index=False))


@app.command()
def report(
    run_id: str | None = typer.Argument(None, help="Run id. Omit with --latest."),
    latest: bool = typer.Option(False, help="Use latest run."),
    out: Path | None = typer.Option(None, help="Output HTML path."),
    store: Path | None = typer.Option(None, help="Local store path."),
) -> None:
    output = generate_report(None if latest or run_id is None else run_id, out=out, store=store)
    typer.echo(str(output))


@app.command()
def ui(
    host: str | None = typer.Option(None, help="Bind host."),
    port: int | None = typer.Option(None, help="Bind port."),
    store: Path | None = typer.Option(None, help="Local store path."),
    no_open: bool = typer.Option(False, help="Do not open a browser window."),
) -> None:
    launch_ui(host=host, port=port, store=store, open_browser=not no_open)


@app.command()
def doctor(store: Path | None = typer.Option(None, help="Local store path.")) -> None:
    config = load_config()
    local_store = LocalStore.from_path(store or config.store)
    index = DuckDBIndex(local_store)
    index.init()
    latest = index.latest_run_id()
    typer.echo(
        json.dumps(
            {
                "store": str(local_store.root),
                "db": str(local_store.db_path),
                "latest_run_id": latest,
                "ui": {"host": config.ui_host, "port": config.ui_port},
                "otel_enabled": config.otel_enabled,
            },
            indent=2,
        )
    )


def _read_frame(path: Path | None) -> pd.DataFrame:
    if path is None:
        raise ValueError("Path is required")
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=suffix == ".jsonl")
    raise ValueError(f"Unsupported dataframe file type: {path.suffix}")


def _read_schema(path: Path | None) -> ForecastSchema | None:
    if path is None:
        return None
    with path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle) or {}
    return ForecastSchema.from_dict(data.get("schema", data))
