const state = {
  runs: [],
  selectedRunId: null,
  activeTab: "metrics",
};

const $ = (selector) => document.querySelector(selector);
const fmt = (value, digits = 3) => {
  if (value === null || value === undefined || value === "") return "";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : String(value);
};

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function boot() {
  const health = await api("/api/health");
  $("#storeInfo").textContent = `Store ${health.store}`;
  await refresh();
  $("#refreshButton").addEventListener("click", refresh);
  $("#projectFilter").addEventListener("change", renderRuns);
  $("#statusFilter").addEventListener("change", renderRuns);
  $("#searchFilter").addEventListener("input", renderRuns);
}

async function refresh() {
  state.runs = await api("/api/runs");
  renderFilters();
  renderRuns();
  if (!state.selectedRunId && state.runs[0]) selectRun(state.runs[0].run_id);
}

function renderFilters() {
  const select = $("#projectFilter");
  const current = select.value;
  const projects = [...new Set(state.runs.map((run) => run.project_id).filter(Boolean))];
  select.innerHTML = `<option value="">All</option>${projects
    .map((project) => `<option value="${escapeHtml(project)}">${escapeHtml(project)}</option>`)
    .join("")}`;
  select.value = current;
}

function filteredRuns() {
  const project = $("#projectFilter").value;
  const status = $("#statusFilter").value;
  const search = $("#searchFilter").value.toLowerCase();
  return state.runs.filter((run) => {
    if (project && run.project_id !== project) return false;
    if (status && run.validation_status !== status) return false;
    if (search) {
      const haystack = [run.run_id, run.project_id, run.model_name, run.model_version, run.adapter_name]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    return true;
  });
}

function renderRuns() {
  const rows = filteredRuns();
  $("#runCount").textContent = `${rows.length} runs`;
  const tbody = $("#runsTable tbody");
  tbody.innerHTML = rows
    .map(
      (run) => `
      <tr data-run-id="${escapeHtml(run.run_id)}" class="${run.run_id === state.selectedRunId ? "selected" : ""}">
        <td>${escapeHtml(shortRun(run.run_id))}</td>
        <td>${escapeHtml(run.project_id || "")}</td>
        <td>${escapeHtml(run.model_name || "")}</td>
        <td>${escapeHtml(run.adapter_name || "")}</td>
        <td>${escapeHtml(formatDate(run.created_at))}</td>
        <td>${escapeHtml(run.horizon_max || "")}</td>
        <td>${fmt(run.points_count, 0)}</td>
        <td>${fmt(run.mae)}</td>
        <td>${fmt(run.wape)}</td>
        <td>${fmt(run.bias)}</td>
        <td>${fmt(run.coverage)}</td>
        <td>${fmt(run.skill_vs_benchmark)}</td>
        <td><span class="pill ${escapeHtml(run.validation_status || "")}">${escapeHtml(run.validation_status || "")}</span></td>
      </tr>
    `
    )
    .join("");
  tbody.querySelectorAll("tr").forEach((row) => {
    row.addEventListener("click", () => selectRun(row.dataset.runId));
  });
}

async function selectRun(runId) {
  state.selectedRunId = runId;
  renderRuns();
  const [run, points, residuals] = await Promise.all([
    api(`/api/runs/${encodeURIComponent(runId)}`),
    api(`/api/runs/${encodeURIComponent(runId)}/forecast-points?limit=2000`),
    api(`/api/runs/${encodeURIComponent(runId)}/residuals?limit=1000`),
  ]);
  renderDetail(run, points, residuals);
}

function renderDetail(run, points, residuals) {
  const metricLookup = Object.fromEntries(
    (run.metrics || [])
      .filter((metric) => metric.slice_name === null)
      .map((metric) => [metric.metric_name, metric.metric_value])
  );
  $("#detail").className = "detail";
  $("#detail").innerHTML = `
    <div class="section-head">
      <div>
        <h2>${escapeHtml(run.model_name || "Run detail")}</h2>
        <p class="eyebrow">${escapeHtml(run.run_id)}</p>
      </div>
      <span class="pill ${escapeHtml(run.status || "")}">${escapeHtml((run.status || "").toUpperCase())}</span>
    </div>
    <div class="summary-grid">
      ${metricCard("MAE", metricLookup.mae)}
      ${metricCard("RMSE", metricLookup.rmse)}
      ${metricCard("WAPE", metricLookup.wape)}
      ${metricCard("Coverage", metricLookup.coverage)}
    </div>
    <div class="detail-grid">
      <div>
        <div class="chart-panel"><div id="forecastChart" class="chart"></div></div>
        <div class="tabs">
          ${tabButton("metrics", "Metrics")}
          ${tabButton("validation", "Validation")}
          ${tabButton("residuals", "Residuals")}
          ${tabButton("artifacts", "Artifacts")}
        </div>
        <div id="tabContent" class="panel"></div>
      </div>
      <div class="panel">
        <h2>Run</h2>
        ${kv({
          Project: run.project_id,
          Version: run.model_version,
          Adapter: run.adapter_name,
          Cutoff: `${formatDate(run.cutoff_start)} to ${formatDate(run.cutoff_end)}`,
          Target: `${formatDate(run.target_start)} to ${formatDate(run.target_end)}`,
          Series: run.series_count,
          Points: run.points_count,
          Trace: run.trace_id,
        })}
        <h2 style="margin-top:20px">Trace timeline</h2>
        ${traceTimeline(run.spans || [])}
      </div>
    </div>
  `;
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      renderTab(run, residuals);
    });
  });
  drawForecastChart($("#forecastChart"), points);
  renderTab(run, residuals);
}

function renderTab(run, residuals) {
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  });
  const target = $("#tabContent");
  if (state.activeTab === "metrics") target.innerHTML = table(run.metrics || []);
  if (state.activeTab === "validation") target.innerHTML = table(run.validation || []);
  if (state.activeTab === "residuals") target.innerHTML = table(residuals || []);
  if (state.activeTab === "artifacts") target.innerHTML = table(run.artifacts || []);
}

function drawForecastChart(el, points) {
  const clean = points.filter((point) => point.yhat !== null && point.yhat !== undefined);
  if (!clean.length) {
    el.innerHTML = `<div class="empty-state">No chartable points</div>`;
    return;
  }
  const width = el.clientWidth || 900;
  const height = 380;
  const pad = 42;
  const values = [];
  clean.forEach((point) => ["yhat", "actual", "benchmark_yhat", "yhat_lower", "yhat_upper"].forEach((key) => {
    if (point[key] !== null && point[key] !== undefined) values.push(Number(point[key]));
  }));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (index) => pad + (index / Math.max(clean.length - 1, 1)) * (width - pad * 2);
  const y = (value) => height - pad - ((value - min) / span) * (height - pad * 2);
  const path = (key) => {
    let d = "";
    clean.forEach((point, index) => {
      if (point[key] === null || point[key] === undefined) return;
      d += `${d ? "L" : "M"}${x(index)},${y(Number(point[key]))}`;
    });
    return d;
  };
  const band = intervalBand(clean, x, y);
  el.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="100%" role="img" aria-label="Forecast viewer">
      <rect width="${width}" height="${height}" fill="#fff"></rect>
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="#d7ddd6"></line>
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" stroke="#d7ddd6"></line>
      ${band}
      <path d="${path("actual")}" fill="none" stroke="#243f78" stroke-width="2.2"></path>
      <path d="${path("benchmark_yhat")}" fill="none" stroke="#a55c1b" stroke-width="2" stroke-dasharray="7 5"></path>
      <path d="${path("yhat")}" fill="none" stroke="#0c6b5f" stroke-width="2.8"></path>
    </svg>
  `;
}

function intervalBand(points, x, y) {
  const usable = points.filter((point) => point.yhat_lower !== null && point.yhat_upper !== null);
  if (!usable.length) return "";
  const top = usable.map((point, index) => `${index ? "L" : "M"}${x(index)},${y(Number(point.yhat_upper))}`).join("");
  const bottom = usable
    .slice()
    .reverse()
    .map((point, index) => `L${x(usable.length - 1 - index)},${y(Number(point.yhat_lower))}`)
    .join("");
  return `<path d="${top}${bottom}Z" fill="rgba(12,107,95,.13)"></path>`;
}

function metricCard(label, value) {
  return `<div class="metric-card"><span>${escapeHtml(label)}</span><strong>${fmt(value)}</strong></div>`;
}

function tabButton(tab, label) {
  return `<button type="button" data-tab="${tab}" class="${state.activeTab === tab ? "active" : ""}">${label}</button>`;
}

function table(rows) {
  if (!rows.length) return `<p class="empty-state">No rows</p>`;
  const columns = Object.keys(rows[0]).filter((column) => !["metadata_json", "sample_json", "schema_json"].includes(column));
  const header = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(formatCell(row[column]))}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="runs-table-wrap" style="max-height:360px"><table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function kv(values) {
  return `<dl class="kv">${Object.entries(values)
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(formatCell(value))}</dd>`)
    .join("")}</dl>`;
}

function traceTimeline(spans) {
  if (!spans.length) return `<p class="empty-state">No local spans</p>`;
  const max = Math.max(...spans.map((span) => Number(span.duration_ms || 0)), 1);
  return `<div class="trace">${spans
    .map((span) => {
      const width = Math.max(3, (Number(span.duration_ms || 0) / max) * 100);
      return `<div class="trace-row"><span>${escapeHtml(span.span_name)}</span><span class="trace-bar" style="width:${width}%"></span><span>${fmt(span.duration_ms, 1)}ms</span></div>`;
    })
    .join("")}</div>`;
}

function shortRun(runId) {
  if (!runId) return "";
  return runId.length > 34 ? `${runId.slice(0, 18)}…${runId.slice(-10)}` : runId;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function formatCell(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return fmt(value);
  return String(value);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

boot().catch((error) => {
  document.body.innerHTML = `<main class="empty-state"><h1>ForecastOps</h1><p>${escapeHtml(error.message)}</p></main>`;
});

