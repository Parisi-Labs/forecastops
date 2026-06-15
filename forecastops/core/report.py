from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

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
    metrics = _query(index, "select * from evaluation_metrics where run_id = ? order by metric_name", run_id)
    validation = _query(index, "select * from validation_events where run_id = ? order by severity", run_id)
    artifacts = _query(index, "select * from artifacts where run_id = ? order by artifact_type", run_id)

    output = Path(out) if out else local_store.reports_dir / f"{run_id}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _render_html(run_record, forecast, metrics, validation, artifacts),
        encoding="utf-8",
    )
    _update_report_uri(index, run_id, output)
    return output


def _query(index: DuckDBIndex, query: str, *params: Any) -> pd.DataFrame:
    with index.connect(read_only=True) as conn:
        return conn.execute(query, params).fetchdf()


def _update_report_uri(index: DuckDBIndex, run_id: str, output: Path) -> None:
    with index.connect() as conn:
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
  <script>window.FORECASTOPS_REPORT={_json_for_script(chart_payload)};</script>
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


def _json_for_script(value: Any) -> str:
    """JSON safe to embed in an executable HTML script tag."""
    return (
        json.dumps(value, ensure_ascii=True)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _json_safe(record: dict[str, Any]) -> dict[str, Any]:
    return {key: (None if pd.isna(value) else value) for key, value in record.items()}


REPORT_CSS = """
:root{color-scheme:light;--ink:#111111;--muted:#6b6b6b;--faint:#9b9b9b;--line:#e4e4e4;--soft:#f7f7f7;--accent:#2563eb;--ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}header{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;padding:20px 24px;border-bottom:1px solid var(--line)}h1{margin:0;font-size:22px}h2{margin:0 0 10px;font-size:14px;font-weight:600}.eyebrow{margin:0 0 6px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font:11px var(--mono)}.sub{margin:6px 0 0;color:var(--muted);font:12px var(--mono)}.status{border:1px solid var(--line);padding:5px 10px;border-radius:3px;font:600 11px var(--mono);text-transform:uppercase}.status.ok{color:var(--ok)}.status.warning{color:var(--warn)}.status.error{color:var(--bad)}main{max-width:1240px;margin:0 auto;padding:20px 24px 56px}.summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.card{border:1px solid var(--line);border-radius:3px;padding:10px 12px}.card span{display:block;color:var(--muted);font:11px var(--mono);text-transform:uppercase;letter-spacing:.04em}.card strong{display:block;margin-top:4px;font:600 14px var(--mono);overflow-wrap:anywhere}section{margin-top:24px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.chart{height:360px;border:1px solid var(--line);border-radius:3px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:3px}table{border-collapse:collapse;min-width:100%;font:12px var(--mono)}th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}th{background:var(--soft);color:var(--muted);font-weight:500}tbody tr:last-child td{border-bottom:0}pre{white-space:pre-wrap;background:var(--soft);border:1px solid var(--line);border-radius:3px;padding:12px;overflow:auto;font:12px var(--mono)}.empty{color:var(--muted)}
@media(max-width:820px){header{display:block;padding:16px}h1{font-size:19px}.summary,.grid{grid-template-columns:1fr}main{padding:16px}}
"""

REPORT_JS = """
(function(){const el=document.getElementById('chart');const pts=(window.FORECASTOPS_REPORT.points||[]).filter(p=>p.yhat!==null);if(!pts.length){el.innerHTML='<p class="empty" style="padding:16px">No chartable forecast points.</p>';return;}const w=el.clientWidth||900,h=360,pad=42;const values=[];pts.forEach(p=>['yhat','actual','benchmark_yhat','yhat_lower','yhat_upper'].forEach(k=>{if(p[k]!==null)values.push(p[k]);}));const min=Math.min(...values),max=Math.max(...values),span=max-min||1;const x=i=>pad+(i/(Math.max(pts.length-1,1)))*(w-pad*2);const y=v=>h-pad-((v-min)/span)*(h-pad*2);function path(key){let d='';pts.forEach((p,i)=>{if(p[key]===null)return;d+=(d?'L':'M')+x(i)+','+y(p[key]);});return d;}el.innerHTML=`<svg viewBox="0 0 ${w} ${h}" width="100%" height="100%" role="img" aria-label="Forecast chart"><rect x="0" y="0" width="${w}" height="${h}" fill="#fff"/><line x1="${pad}" y1="${h-pad}" x2="${w-pad}" y2="${h-pad}" stroke="#e4e4e4"/><line x1="${pad}" y1="${pad}" x2="${pad}" y2="${h-pad}" stroke="#e4e4e4"/><path d="${path('yhat')}" fill="none" stroke="#2563eb" stroke-width="2"/><path d="${path('actual')}" fill="none" stroke="#111111" stroke-width="1.8"/><path d="${path('benchmark_yhat')}" fill="none" stroke="#9b9b9b" stroke-width="1.5" stroke-dasharray="5 4"/></svg>`;})();
"""
