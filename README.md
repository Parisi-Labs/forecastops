# ForecastOps

[![PyPI](https://img.shields.io/pypi/v/forecastops)](https://pypi.org/project/forecastops/)
[![Python](https://img.shields.io/pypi/pyversions/forecastops)](https://pypi.org/project/forecastops/)
[![CI](https://github.com/Parisi-Labs/forecastops/actions/workflows/ci.yml/badge.svg)](https://github.com/Parisi-Labs/forecastops/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

ForecastOps is a local-first observability and evaluation layer for
production forecasts. It works with the forecasting code you already have.

Add one line after `.predict()`, then run `fops ui`.

```python
import forecastops as fops

forecast = model.predict(future)

run = fops.capture(
    forecast,
    project="site-traffic",
    series_id="homepage",
    cutoff=train_df["ds"].max(),
    actuals=actuals_df,
)
```

```bash
fops ui
```

ForecastOps stores forecast artifacts locally as Parquet, writes run metadata
to DuckDB, computes horizon-aware metrics, generates static HTML reports, and
serves a read-only local UI. It does not train forecasting models, require a
cloud account, or upload raw forecast data.

## Install

From [PyPI](https://pypi.org/project/forecastops/):

```bash
pip install forecastops
```

From source:

```bash
git clone https://github.com/Parisi-Labs/forecastops.git
cd forecastops
pip install -e .
```

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python examples/generic_dataframe.py
fops report --latest
fops ui
```

Open [http://127.0.0.1:4784](http://127.0.0.1:4784) after starting the UI.

## Local UI

<img width="3520" height="2394" alt="CleanShot 2026-06-12 at 10 45 00@2x" src="https://github.com/user-attachments/assets/0115c5fe-260f-4eb1-8033-63da784651bf" />

`fops ui` serves a read-only explorer for the local store:

- **Runs** — every captured run with horizon, points, MAE, WAPE, bias,
  coverage, skill, and validation status; filterable and sortable.
- **Run detail** — headline metrics, a forecast inspector with one chart per
  series (forecast vs. actual vs. benchmark with interval bands), metrics,
  validation events, residuals, artifacts, and the capture trace timeline.
- **Projects** — runs grouped by project with error trends across captures.
- **Groups** — experiment and backtest groups with run counts and mean error;
  click through to the grouped runs.
- **Compare** — metric deltas and regressions between any two runs, backed
  by `fops diff`.

## Core Concepts

- `capture`: normalize forecasts from existing workflows.
- `ForecastSchema`: map arbitrary dataframe columns to canonical semantics.
- `validate`: catch schema, timestamp, duplicate, interval, and leakage issues.
- `evaluate`: compute MAE, RMSE, WAPE, sMAPE, bias, coverage, interval width,
  pinball loss (for quantile forecasts), and count — sliced by horizon and by
  any categorical columns you keep (e.g. region, holiday_flag, event_type).
- `compare`: calculate benchmark metrics and skill.
- `backtest`: evaluate a rolling-origin forecast panel as one grouped run set,
  with per-cutoff and aggregate (mean/std) metrics.
- `diff`: compare two captured runs.
- groups: tag related runs with `capture(group=...)` (or a `backtest`) and
  browse them together in the UI.
- local store: `.forecastops/forecastops.duckdb` plus Parquet artifacts.
- UI: local read-only browser explorer for runs, metrics, residuals, validation,
  artifacts, and run differences.

## Privacy Defaults

ForecastOps is local-first by default:

- binds the UI to `127.0.0.1` and refuses other hosts unless you pass
  `--allow-remote`
- makes no outbound network calls
- stores raw forecast points in the configured local store
- emits OpenTelemetry only when explicitly enabled
- avoids raw forecast points in telemetry

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy forecastops
```

## License

Apache-2.0. See [LICENSE](LICENSE).
