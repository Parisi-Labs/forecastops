from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from forecastops.cli.main import app
from forecastops.ui import server as ui_server

runner = CliRunner()


def _write_forecast_csv(path: Path, values: list[float]) -> Path:
    lines = ["ds,yhat"]
    lines += [f"2026-01-{2 + offset:02d},{value}" for offset, value in enumerate(values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_actuals_csv(path: Path, values: list[float]) -> Path:
    lines = ["target_time,actual"]
    lines += [f"2026-01-{2 + offset:02d},{value}" for offset, value in enumerate(values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _capture_run(tmp_path: Path, values: list[float], name: str = "forecast") -> str:
    csv_path = _write_forecast_csv(tmp_path / f"{name}.csv", values)
    result = runner.invoke(
        app,
        [
            "capture",
            str(csv_path),
            "--project",
            "cli-test",
            "--cutoff",
            "2026-01-01",
            "--series-id",
            "series-a",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    return payload["run_id"]


def test_capture_from_csv_writes_into_isolated_store(
    isolated_store: Path, tmp_path: Path
) -> None:
    run_id = _capture_run(tmp_path, [1.0, 2.0, 3.0])

    assert run_id
    assert (isolated_store / "forecastops.duckdb").exists()


def test_capture_with_explicit_store_option(tmp_path: Path) -> None:
    csv_path = _write_forecast_csv(tmp_path / "forecast.csv", [1.0, 2.0])
    store = tmp_path / "explicit-store"
    result = runner.invoke(
        app,
        [
            "capture",
            str(csv_path),
            "--cutoff",
            "2026-01-01",
            "--series-id",
            "series-a",
            "--store",
            str(store),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (store / "forecastops.duckdb").exists()


def test_report_latest(isolated_store: Path, tmp_path: Path) -> None:
    _capture_run(tmp_path, [1.0, 2.0, 3.0])

    result = runner.invoke(app, ["report", "--latest"])

    assert result.exit_code == 0, result.output
    report_path = Path(result.output.strip())
    assert report_path.exists()
    assert report_path.suffix == ".html"
    assert isolated_store in report_path.parents


def test_evaluate_with_actuals(isolated_store: Path, tmp_path: Path) -> None:
    run_id = _capture_run(tmp_path, [1.0, 2.0, 3.0])
    actuals_path = _write_actuals_csv(tmp_path / "actuals.csv", [1.5, 1.5, 3.5])

    result = runner.invoke(app, ["evaluate", run_id, "--actuals", str(actuals_path)])

    assert result.exit_code == 0, result.output
    assert "mae" in result.output


def test_evaluate_unknown_run_fails(isolated_store: Path) -> None:
    result = runner.invoke(app, ["evaluate", "missing-run"])

    assert result.exit_code != 0


def test_diff_between_two_runs(isolated_store: Path, tmp_path: Path) -> None:
    base_run_id = _capture_run(tmp_path, [1.0, 2.0, 3.0], name="base")
    candidate_run_id = _capture_run(tmp_path, [1.5, 2.5, 3.5], name="candidate")

    result = runner.invoke(app, ["diff", base_run_id, candidate_run_id])

    assert result.exit_code == 0, result.output
    assert "delta" in result.output


def test_ui_refuses_non_loopback_host(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("uvicorn.run must not be reached for a refused host")

    monkeypatch.setattr(ui_server.uvicorn, "run", _fail)

    result = runner.invoke(app, ["ui", "--host", "0.0.0.0", "--no-open"])

    assert result.exit_code != 0
    assert isinstance(result.exception, SystemExit)
    assert "non-loopback" in str(result.exception)


def test_ui_allow_remote_passes_gate(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def _record(app_obj: object, **kwargs: object) -> None:
        calls.append({"app": app_obj, **kwargs})

    monkeypatch.setattr(ui_server.uvicorn, "run", _record)

    result = runner.invoke(app, ["ui", "--host", "0.0.0.0", "--allow-remote", "--no-open"])

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["host"] == "0.0.0.0"


def test_ui_default_loopback_host_allowed(
    isolated_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def _record(app_obj: object, **kwargs: object) -> None:
        calls.append({"app": app_obj, **kwargs})

    monkeypatch.setattr(ui_server.uvicorn, "run", _record)

    result = runner.invoke(app, ["ui", "--no-open"])

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1"
