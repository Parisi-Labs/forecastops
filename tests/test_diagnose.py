from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

import forecastops as fops
from forecastops.cli.main import app

runner = CliRunner()


def _capture_regime_run(store: Path) -> str:
    times = pd.date_range("2026-01-02", periods=4, freq="D")
    forecast = pd.DataFrame(
        {
            "series_id": ["east"] * 4 + ["west"] * 4,
            "target_time": list(times) * 2,
            "prediction": [10.0, 11.0, 12.0, 13.0, 20.0, 21.0, 22.0, 23.0],
            "region": ["east"] * 4 + ["west"] * 4,
        }
    )
    actuals = pd.DataFrame(
        {
            "series_id": ["east"] * 4 + ["west"] * 4,
            "target_time": list(times) * 2,
            "actual": [10.5, 10.5, 12.5, 12.5, 30.0, 10.0, 35.0, 12.0],
        }
    )
    run = fops.capture(
        forecast,
        project="diag",
        schema=fops.ForecastSchema(
            series_id="series_id",
            target_time="target_time",
            prediction="prediction",
            extra_columns=["region"],
        ),
        cutoff=pd.Timestamp("2026-01-01"),
        actuals=actuals,
        model_name="m1",
        group="sweep",
        store=store,
    )
    return run.run_id


def test_diagnose_structure(isolated_store: Path) -> None:
    run_id = _capture_regime_run(isolated_store)
    d = fops.diagnose(run_id, store=isolated_store)

    assert d["run_id"] == run_id
    assert d["project"] == "diag"
    assert d["group"] == "sweep"
    assert d["model"] == "m1"
    assert "mae" in d["overall"] and "wape" in d["overall"]
    assert d["data"]["series_count"] == 2
    assert d["data"]["points_count"] == 8

    # west has much larger errors than east → it should be the worst series.
    assert d["worst_series"][0]["series_id"] == "west"
    assert d["worst_series"][0]["wape"] >= d["worst_series"][-1]["wape"]

    # regime breakdown by the preserved "region" column is present and sorted desc.
    regimes = d["worst_regimes"]
    assert {r["value"] for r in regimes} == {"east", "west"}
    assert regimes == sorted(regimes, key=lambda r: r["wape"], reverse=True)

    assert d["validation"]["status"] in {"PASS", "WARN", "FAIL"}
    assert "forecast" in d["artifacts"]


def test_root_span_carries_rich_context(isolated_store: Path) -> None:
    import json as _json

    from forecastops.store.duckdb_index import DuckDBIndex
    from forecastops.store.local import LocalStore

    run_id = _capture_regime_run(isolated_store)
    index = DuckDBIndex(LocalStore.from_path(isolated_store))
    with index.connect(read_only=True) as conn:
        row = conn.execute(
            "select attributes_json from spans where run_id = ? and span_name = 'forecast.run'",
            [run_id],
        ).fetchone()
    attrs = _json.loads(row[0])
    # Beyond project/run/kind, the root span now carries the run's semantic state.
    for key in [
        "forecast.adapter.name",
        "forecast.group.name",
        "forecast.series.count",
        "forecast.points.count",
        "forecast.validation.status",
        "forecast.artifact.forecast.uri",
        "forecast.cutoff.start",
        "forecast.target.end",
    ]:
        assert key in attrs, f"missing trace attribute {key}"
    assert attrs["forecast.group.name"] == "sweep"
    assert int(attrs["forecast.series.count"]) == 2


def test_diagnose_unknown_run(isolated_store: Path) -> None:
    try:
        fops.diagnose("nope", store=isolated_store)
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown run")


def test_cli_diagnose(isolated_store: Path) -> None:
    run_id = _capture_regime_run(isolated_store)
    result = runner.invoke(app, ["diagnose", run_id, "--store", str(isolated_store)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == run_id
    assert payload["worst_series"]


def test_cli_backtest(isolated_store: Path, tmp_path: Path) -> None:
    windows, acts = [], []
    for cutoff, start in [("2026-01-01", "2026-01-02"), ("2026-01-08", "2026-01-09")]:
        times = pd.date_range(start, periods=3, freq="D")
        windows.append(
            pd.DataFrame(
                {
                    "series_id": "s",
                    "cutoff": pd.Timestamp(cutoff),
                    "target_time": times,
                    "prediction": [10.0, 11.0, 12.0],
                }
            )
        )
        acts.append(pd.DataFrame({"series_id": "s", "target_time": times, "actual": [10.5, 11.5, 11.0]}))
    panel = pd.concat(windows, ignore_index=True)
    actuals = pd.concat(acts, ignore_index=True)
    panel_path = tmp_path / "panel.parquet"
    actuals_path = tmp_path / "actuals.parquet"
    panel.to_parquet(panel_path)
    actuals.to_parquet(actuals_path)
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(
        "series_id: series_id\ntarget_time: target_time\nprediction: prediction\n", encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "backtest",
            str(panel_path),
            "--group",
            "rolling",
            "--project",
            "bt",
            "--schema",
            str(schema_path),
            "--actuals",
            str(actuals_path),
            "--store",
            str(isolated_store),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["windows"] == 2
    assert payload["group_id"] == "bt::rolling"
