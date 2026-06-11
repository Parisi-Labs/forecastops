from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from forecastops.core.run import ForecastRun
from forecastops.store.duckdb_index import DuckDBIndex
from forecastops.store.local import LocalStore
from forecastops.store.parquet import read_artifact


def report(
    run: ForecastRun | str | None = None,
    *,
    out: str | Path | None = None,
    store: str | Path | None = None,
) -> Path:
    local_store = LocalStore.from_path(store)
    index = DuckDBIndex(local_store)
    index.init()
    if isinstance(run, ForecastRun):
        run_id = run.run_id
    elif isinstance(run, str):
        run_id = run
    else:
        latest = index.latest_run_id()
        if latest is None:
            raise ValueError("No ForecastOps runs found")
        run_id = latest
    run_record = index.run_by_id(run_id)
    if run_record is None:
        raise ValueError(f"Run {run_id!r} not found")

    forecast = read_artifact(run_record["forecast_artifact_uri"])
    metrics = _query(index.path, "select * from evaluation_metrics where run_id = ? order by metric_name", run_id)
    validation = _query(index.path, "select * from validation_events where run_id = ? order by severity", run_id)
    artifacts = _query(index.path, "select * from artifacts where run_id = ? order by artifact_type", run_id)

    output = Path(out) if out else local_store.reports_dir / f"{run_id}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _render_html(run_record, forecast, metrics, validation, artifacts),
        encoding="utf-8",
    )
    _update_report_uri(index.path, run_id, output)
    return output


def _query(db_path: Path, query: str, *params: Any) -> pd.DataFrame:
    with duckdb.connect(str(db_path), read_only=True) as conn:
        return conn.execute(query, params).fetchdf()


def _update_report_uri(db_path: Path, run_id: str, output: Path) -> None:
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("update runs set report_uri = ? where run_id = ?", [str(output.resolve()), run_id])


def _render_html(
    run: dict[str, Any],
    forecast: pd.DataFrame,
    metrics: pd.DataFrame,
    validation: pd.DataFrame,
    artifacts: pd.DataFrame,
) -> str:
    sample = forecast.sort_values(["series_id", "target_time"]).head(500)
    chart_payload = {
        "points": [
            {
                "series_id": str(row.get("series_id")),
                "target_time": str(row.get("target_time")),
                "yhat": _num(row.get("yhat")),
                "actual": _num(row.get("actual")),
                "benchmark_yhat": _num(row.get("benchmark_yhat")),
                "yhat_lower": _num(row.get("yhat_lower")),
                "yhat_upper": _num(row.get("yhat_upper")),
            }
            for _, row in sample.iterrows()
        ]
    }
    title = f"ForecastOps Report - {run['run_id']}"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{REPORT_CSS}</style>
</head>
<body>
  <header>
    <div>
      <p class="eyebrow">Local ForecastOps report</p>
      <h1>{html.escape(str(run['project_id']))}</h1>
      <p class="sub">{html.escape(str(run['run_id']))}</p>
    </div>
    <div class="status {html.escape(str(run['status']))}">{html.escape(str(run['status']).upper())}</div>
  </header>
  <main>
    <section class="summary">
      {_summary_card("Model", run.get("model_name"))}
      {_summary_card("Adapter", run.get("adapter_name"))}
      {_summary_card("Series", run.get("series_count"))}
      {_summary_card("Points", run.get("points_count"))}
      {_summary_card("Cutoff", f"{run.get('cutoff_start')} to {run.get('cutoff_end')}")}
      {_summary_card("Target", f"{run.get('target_start')} to {run.get('target_end')}")}
    </section>
    <section>
      <h2>Forecast vs actual</h2>
      <div id="chart" class="chart"></div>
    </section>
    <section class="grid">
      <div>
        <h2>Metrics</h2>
        {_table(metrics)}
      </div>
      <div>
        <h2>Validation</h2>
        {_table(validation)}
      </div>
    </section>
    <section>
      <h2>Artifacts</h2>
      {_table(artifacts)}
    </section>
    <section>
      <h2>Reproducibility metadata</h2>
      <pre>{html.escape(json.dumps(_json_safe(run), indent=2, default=str))}</pre>
    </section>
  </main>
  <script>window.FORECASTOPS_REPORT={json.dumps(chart_payload)};</script>
  <script>{REPORT_JS}</script>
</body>
</html>
"""


def _summary_card(label: str, value: Any) -> str:
    return f"<div class='card'><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>"


def _table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "<p class='empty'>No rows.</p>"
    preview = frame.copy()
    for column in preview.columns:
        preview[column] = preview[column].map(lambda value: "" if pd.isna(value) else str(value))
    headers = "".join(f"<th>{html.escape(str(column))}</th>" for column in preview.columns)
    rows = []
    for _, row in preview.iterrows():
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in row)
        rows.append(f"<tr>{cells}</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _num(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_safe(record: dict[str, Any]) -> dict[str, Any]:
    return {key: (None if pd.isna(value) else value) for key, value in record.items()}


REPORT_CSS = """
:root{color-scheme:light;--ink:#16211d;--muted:#5e6b65;--line:#d8ded8;--paper:#f7f7f2;--panel:#ffffff;--accent:#116a5c;--warn:#a96700;--bad:#a33333}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:Georgia,'Times New Roman',serif}header{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;padding:42px 48px 28px;border-bottom:1px solid var(--line);background:#fff}h1{margin:0;font-size:44px;letter-spacing:0}h2{margin:0 0 14px;font-size:21px}.eyebrow{margin:0 0 8px;text-transform:uppercase;letter-spacing:.08em;color:var(--accent);font:700 12px ui-monospace,monospace}.sub{margin:8px 0 0;color:var(--muted);font:13px ui-monospace,monospace}.status{border:1px solid var(--line);padding:10px 14px;border-radius:6px;font:700 12px ui-monospace,monospace}.status.ok{color:var(--accent)}.status.warning{color:var(--warn)}.status.error{color:var(--bad)}main{max-width:1240px;margin:0 auto;padding:28px 28px 64px}.summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:15px}.card span{display:block;color:var(--muted);font:12px ui-monospace,monospace;text-transform:uppercase}.card strong{display:block;margin-top:8px;font-size:17px;overflow-wrap:anywhere}section{margin-top:28px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.chart{height:360px;background:#fff;border:1px solid var(--line);border-radius:6px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:6px;background:#fff}table{border-collapse:collapse;min-width:100%;font:13px ui-monospace,monospace}th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}th{background:#eef2eb;color:#26322e}pre{white-space:pre-wrap;background:#fff;border:1px solid var(--line);border-radius:6px;padding:16px;overflow:auto}.empty{color:var(--muted)}
@media(max-width:820px){header{padding:28px 22px;display:block}h1{font-size:34px}.summary,.grid{grid-template-columns:1fr}main{padding:22px}}
"""

REPORT_JS = """
(function(){const el=document.getElementById('chart');const pts=(window.FORECASTOPS_REPORT.points||[]).filter(p=>p.yhat!==null);if(!pts.length){el.innerHTML='<p class="empty" style="padding:16px">No chartable forecast points.</p>';return;}const w=el.clientWidth||900,h=360,pad=42;const values=[];pts.forEach(p=>['yhat','actual','benchmark_yhat','yhat_lower','yhat_upper'].forEach(k=>{if(p[k]!==null)values.push(p[k]);}));const min=Math.min(...values),max=Math.max(...values),span=max-min||1;const x=i=>pad+(i/(Math.max(pts.length-1,1)))*(w-pad*2);const y=v=>h-pad-((v-min)/span)*(h-pad*2);function path(key){let d='';pts.forEach((p,i)=>{if(p[key]===null)return;d+=(d?'L':'M')+x(i)+','+y(p[key]);});return d;}el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%" height="100%" role="img" aria-label="Forecast chart"><rect x="0" y="0" width="${w}" height="${h}" fill="#fff"/><line x1="${pad}" y1="${h-pad}" x2="${w-pad}" y2="${h-pad}" stroke="#d8ded8"/><line x1="${pad}" y1="${pad}" x2="${pad}" y2="${h-pad}" stroke="#d8ded8"/><path d="${path('yhat')}" fill="none" stroke="#116a5c" stroke-width="2.5"/><path d="${path('actual')}" fill="none" stroke="#1d2c4d" stroke-width="2"/><path d="${path('benchmark_yhat')}" fill="none" stroke="#a96700" stroke-width="1.8" stroke-dasharray="6 5"/></svg>`;})();
"""

