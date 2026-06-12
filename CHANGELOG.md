# Changelog

## Unreleased

### Added

- `sMAPE` and `pinball` (quantile) loss metrics. sMAPE is a scale-free ratio
  alongside WAPE; pinball loss is averaged over `yhat_p<level>` quantile
  columns and is skipped for point forecasts.
- Metrics are now sliced by any categorical columns preserved via a schema's
  `extra_columns` (e.g. region, holiday_flag, event_type), in addition to
  horizon buckets, so error-by-regime breakdowns appear automatically.
- Experiment groups: `capture(group="...")` tags related runs into a named
  group, with a new Groups view in the UI and a `/api/groups` endpoint.
- `fops.backtest(...)`: evaluate a rolling-origin forecast panel as one
  grouped backtest, returning per-cutoff and aggregate (mean/std) metrics.
  Existing stores are migrated in place to add the group columns.
- Diagnostics cockpit on the run detail page: residual histogram, error by
  horizon, per-series worst offenders, and per-regime MAE breakdowns.
- Group detail page showing per-metric mean ± std and stability across a
  group's runs (e.g. a backtest across windows).

### Changed

- The Nixtla adapter now parses `<model>-lo-<level>`/`<model>-hi-<level>`
  prediction-interval columns into interval bounds and per-level quantile
  columns, so coverage, interval width, and pinball loss work for
  statsforecast/neuralforecast outputs.

## 0.1.0 — 2026-06-11

Initial public release.

### Highlights

- `fops.capture()` normalizes forecasts from existing pipelines into local
  Parquet artifacts with a DuckDB run index; `evaluate`, `compare`, and `diff`
  compute horizon-aware metrics, benchmark skill, and run-to-run deltas.
- Local read-only UI (`fops ui`) with Runs, run detail (per-series forecast
  inspector), Projects (error trends across captures), and Compare views.
- Static HTML reports (`fops report`) and an `fops` CLI for capture, lint,
  evaluate, diff, and report workflows.
- Optional OpenTelemetry export of aggregate metrics and capture traces —
  off by default, never includes raw forecast points.

### Hardening before release

- Merges between forecasts and actuals/benchmarks now align timezones,
  reject duplicate join keys with a clear error, and warn when a join
  matches zero rows instead of silently reporting nothing.
- Benchmarked captures no longer evaluate twice, keep the `count` metric,
  and aggregate views report model-side metrics (benchmark values are
  reported separately).
- Read connections retry while a capture holds the DuckDB write lock, so
  the UI and reports work during captures.
- UI queries push filters into DuckDB instead of loading whole Parquet
  artifacts, and residuals are computed over the full artifact (previously
  silently truncated at 10,000 points).
- OpenTelemetry metrics actually export through the global meter provider
  (gauges, so negative values like bias work); traces and metrics share one
  config-driven enable switch; `forecastops.otel.configure_console_export()`
  sets up a console exporter for local testing.
- The UI refuses to bind to non-loopback hosts unless `--allow-remote` is
  passed.
- `ForecastSchema.from_dict` rejects unknown keys; quantile column detection
  no longer mangles columns like `yhat_pred`; `@fops.forecast` returns the
  wrapped function's original output (pass `return_run=True` for the run);
  `evaluate`/`compare`/`diff` accept frames without a `run_id`.
- Removed the unused `jinja2` dependency.
