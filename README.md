# ForecastOps

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

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all]"
python examples/generic_dataframe.py
fops report --latest
fops ui
```

Open [http://127.0.0.1:4784](http://127.0.0.1:4784) after starting the UI.

## Core Concepts

- `capture`: normalize forecasts from existing workflows.
- `ForecastSchema`: map arbitrary dataframe columns to canonical semantics.
- `validate`: catch schema, timestamp, duplicate, interval, and leakage issues.
- `evaluate`: compute MAE, RMSE, WAPE, bias, coverage, interval width, and count.
- `compare`: calculate benchmark metrics and skill.
- `diff`: compare two captured runs.
- local store: `.forecastops/forecastops.duckdb` plus Parquet artifacts.
- UI: local read-only browser explorer for runs, metrics, residuals, validation,
  artifacts, and run differences.

## Privacy Defaults

ForecastOps is local-first by default:

- binds the UI to `127.0.0.1`
- makes no outbound network calls
- stores raw forecast points in the configured local store
- emits OpenTelemetry only when explicitly enabled
- avoids raw forecast points in telemetry

