from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from fastapi.testclient import TestClient

import forecastops as fops
from forecastops.core.report import report
from forecastops.ui.server import create_app


def test_capture_persists_artifacts_metrics_and_report(isolated_store: Path) -> None:
    cutoff = pd.Timestamp("2026-01-01")
    forecast = pd.DataFrame(
        {
            "target_time": pd.date_range("2026-01-02", periods=4, freq="D"),
            "prediction": [10.0, 11.0, 12.0, 13.0],
            "yhat_lower": [8.0, 9.0, 10.0, 11.0],
            "yhat_upper": [12.0, 13.0, 14.0, 15.0],
            "region": ["east"] * 4,
        }
    )
    actuals = pd.DataFrame(
        {
            "target_time": pd.date_range("2026-01-02", periods=4, freq="D"),
            "actual": [10.5, 10.5, 12.5, 12.5],
        }
    )

    run = fops.capture(
        forecast,
        project="capture-test",
        schema=fops.ForecastSchema(
            target_time="target_time",
            prediction="prediction",
            lower="yhat_lower",
            upper="yhat_upper",
            extra_columns=["region"],
        ),
        cutoff=cutoff,
        series_id="series-a",
        actuals=actuals,
        model_name="baseline",
        store=isolated_store,
    )

    assert Path(run.forecast_artifact_uri).exists()
    assert run.metrics
    assert any(metric.metric_name == "mae" for metric in run.metrics)

    with duckdb.connect(str(isolated_store / "forecastops.duckdb"), read_only=True) as conn:
        runs = conn.execute("select count(*) from runs").fetchone()[0]
        artifacts = conn.execute("select count(*) from artifacts where run_id = ?", [run.run_id]).fetchone()[0]
    assert runs == 1
    assert artifacts >= 2

    report_path = report(run, store=isolated_store)
    assert report_path.exists()
    assert "Forecast vs actual" in report_path.read_text(encoding="utf-8")


def test_report_escapes_json_script_payload(isolated_store: Path) -> None:
    malicious_series = '</script><script>window.FORECASTOPS_PWNED=1</script>'
    run = fops.capture(
        pd.DataFrame(
            {
                "series_id": [malicious_series],
                "target_time": [pd.Timestamp("2026-01-02")],
                "yhat": [1.0],
            }
        ),
        project="report-escape-test",
        cutoff=pd.Timestamp("2026-01-01"),
        store=isolated_store,
    )

    rendered = report(run, store=isolated_store).read_text(encoding="utf-8")

    assert malicious_series not in rendered
    assert "\\u003c/script\\u003e\\u003cscript\\u003ewindow.FORECASTOPS_PWNED=1" in rendered


def test_ui_api_smoke(isolated_store: Path) -> None:
    cutoff = pd.Timestamp("2026-01-01")
    run = fops.capture(
        pd.DataFrame({"ds": pd.date_range("2026-01-02", periods=2), "yhat": [1.0, 2.0]}),
        project="ui-test",
        series_id="homepage",
        cutoff=cutoff,
        store=isolated_store,
    )
    client = TestClient(create_app(store=isolated_store))

    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/runs").json()[0]["run_id"] == run.run_id
    assert client.get(f"/api/runs/{run.run_id}").json()["run_id"] == run.run_id
    assert len(client.get(f"/api/runs/{run.run_id}/forecast-points").json()) == 2
