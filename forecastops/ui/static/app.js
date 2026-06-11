const state = {
  runs: [],
  filters: { project: "", status: "", search: "" },
  sort: { key: "created_at", dir: "desc" },
  runTab: "metrics",
  detail: null, // { run, points, residuals, series, selectedSeries }
};

const COLORS = {
  forecast: "#4c8dff",
  actual: "#fb923c",
  benchmark: "#8b939e",
  band: "rgba(76, 141, 255, .15)",
  grid: "#1c2129",
  axis: "#232a33",
  tick: "#5c6470",
  guide: "#8b939e",
};

const MAX_GRID_SERIES = 12;

const $ = (selector) => document.querySelector(selector);

const fmt = (value, digits = 3) => {
  if (value === null || value === undefined || value === "") return "–";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : String(value);
};

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

/* Routing: #/runs, #/runs/<id>, #/projects, #/compare?base=..&candidate=.. */

function parseHash() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const [pathPart, queryPart] = hash.split("?");
  const segments = pathPart.split("/").filter(Boolean).map(decodeURIComponent);
  return { segments, params: new URLSearchParams(queryPart || "") };
}

async function route() {
  const { segments, params } = parseHash();
  const view = segments[0] || "runs";
  document.querySelectorAll(".nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.view === view);
  });
  $("#topMeta").textContent = "";
  if (view === "runs" && segments[1]) {
    await renderRunView(segments[1]);
  } else if (view === "projects") {
    renderProjectsView();
  } else if (view === "compare") {
    renderCompareView(params);
  } else {
    renderRunsView(params);
  }
}

function setCrumbs(html) {
  $("#crumbs").innerHTML = html;
}

async function boot() {
  const health = await api("/api/health");
  $("#storeInfo").textContent = health.store;
  $("#refreshButton").addEventListener("click", async () => {
    await refreshData();
    await route();
  });
  window.addEventListener("hashchange", route);
  await refreshData();
  await route();
}

async function refreshData() {
  state.runs = await api("/api/runs");
}

/* ---------- Runs index ---------- */

function renderRunsView(params) {
  setCrumbs("Runs");
  if (params && params.has("project")) state.filters.project = params.get("project");
  if (!state.runs.length) {
    $("#view").innerHTML = emptyStoreHtml();
    return;
  }
  const projects = [...new Set(state.runs.map((run) => run.project_id).filter(Boolean))].sort();
  $("#view").innerHTML = `
    <div class="toolbar">
      <select id="projectFilter" aria-label="Filter by project">
        <option value="">All projects</option>
        ${projects.map((p) => `<option value="${escapeHtml(p)}" ${p === state.filters.project ? "selected" : ""}>${escapeHtml(p)}</option>`).join("")}
      </select>
      <select id="statusFilter" aria-label="Filter by validation status">
        <option value="">All statuses</option>
        ${["PASS", "WARN", "FAIL"].map((s) => `<option value="${s}" ${s === state.filters.status ? "selected" : ""}>${s[0]}${s.slice(1).toLowerCase()}</option>`).join("")}
      </select>
      <input id="searchFilter" type="search" placeholder="Search run, project, model, adapter" autocomplete="off" value="${escapeHtml(state.filters.search)}" aria-label="Search runs">
    </div>
    <div class="table-wrap runs-table-wrap">
      <table id="runsTable">
        <thead>
          <tr>
            <th data-sort="run_id">Run</th>
            <th data-sort="project_id">Project</th>
            <th data-sort="model_name">Model</th>
            <th data-sort="created_at">Created</th>
            <th data-sort="horizon_max" class="num">Horizon</th>
            <th data-sort="points_count" class="num">Points</th>
            <th data-sort="mae" class="num">MAE</th>
            <th data-sort="wape" class="num">WAPE</th>
            <th data-sort="bias" class="num">Bias</th>
            <th data-sort="coverage" class="num">Coverage</th>
            <th data-sort="skill_vs_benchmark" class="num">Skill</th>
            <th data-sort="validation_status">Validation</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </div>
  `;
  $("#projectFilter").addEventListener("change", (event) => {
    state.filters.project = event.target.value;
    updateRunsTable();
  });
  $("#statusFilter").addEventListener("change", (event) => {
    state.filters.status = event.target.value;
    updateRunsTable();
  });
  $("#searchFilter").addEventListener("input", (event) => {
    state.filters.search = event.target.value;
    updateRunsTable();
  });
  document.querySelectorAll("#runsTable th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sort.key === key) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort = { key, dir: key === "created_at" ? "desc" : "asc" };
      }
      updateRunsTable();
    });
  });
  updateRunsTable();
}

function filteredRuns() {
  const { project, status, search } = state.filters;
  const needle = search.toLowerCase();
  return state.runs.filter((run) => {
    if (project && run.project_id !== project) return false;
    if (status && run.validation_status !== status) return false;
    if (needle) {
      const haystack = [run.run_id, run.project_id, run.model_name, run.model_version, run.adapter_name]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
}

function sortedRuns(rows) {
  const { key, dir } = state.sort;
  const factor = dir === "asc" ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const va = a[key];
    const vb = b[key];
    if (va === null || va === undefined || va === "") return 1;
    if (vb === null || vb === undefined || vb === "") return -1;
    const na = Number(va);
    const nb = Number(vb);
    if (Number.isFinite(na) && Number.isFinite(nb)) return (na - nb) * factor;
    return String(va).localeCompare(String(vb)) * factor;
  });
}

function updateRunsTable() {
  const rows = sortedRuns(filteredRuns());
  $("#topMeta").textContent = `${rows.length} of ${state.runs.length} runs`;
  document.querySelectorAll("#runsTable th[data-sort]").forEach((th) => {
    const active = th.dataset.sort === state.sort.key;
    th.classList.toggle("sorted", active);
    const base = th.textContent.replace(/ [↑↓]$/, "");
    th.textContent = active ? `${base} ${state.sort.dir === "asc" ? "↑" : "↓"}` : base;
  });
  const tbody = $("#runsTable tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="12" style="color:var(--muted)">No runs match the current filters.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map(
      (run) => `
      <tr data-href="#/runs/${encodeURIComponent(run.run_id)}">
        <td title="${escapeHtml(run.run_id)}"><span class="link">${escapeHtml(shortRun(run.run_id))}</span></td>
        <td>${escapeHtml(run.project_id || "–")}</td>
        <td>${escapeHtml(run.model_name || "–")}</td>
        <td title="${escapeHtml(String(run.created_at || ""))}">${escapeHtml(formatDate(run.created_at))}</td>
        <td class="num">${escapeHtml(String(run.horizon_max ?? "–"))}</td>
        <td class="num">${fmt(run.points_count, 0)}</td>
        <td class="num">${fmt(run.mae)}</td>
        <td class="num">${fmt(run.wape)}</td>
        <td class="num">${fmt(run.bias)}</td>
        <td class="num">${fmt(run.coverage)}</td>
        <td class="num">${fmt(run.skill_vs_benchmark)}</td>
        <td><span class="status ${escapeHtml(run.validation_status || "")}">${escapeHtml(run.validation_status || "–")}</span></td>
      </tr>
    `
    )
    .join("");
  attachRowLinks(tbody);
}

function attachRowLinks(scope) {
  scope.querySelectorAll("tr[data-href]").forEach((row) => {
    row.addEventListener("click", () => {
      window.location.hash = row.dataset.href;
    });
  });
}

function emptyStoreHtml() {
  return `
    <div class="empty-state">
      <h2>No runs captured yet</h2>
      <p>Capture a forecast from your existing pipeline, then refresh this page:</p>
      <pre>import forecastops as fops

forecast = model.predict(future)

fops.capture(
    forecast,
    project="my-project",
    series_id="my-series",
    cutoff=train_df["ds"].max(),
    actuals=actuals_df,
)</pre>
      <p class="hint">Runs are stored locally in the store shown in the sidebar. Nothing leaves this machine.</p>
    </div>
  `;
}

/* ---------- Run detail ---------- */

async function renderRunView(runId) {
  setCrumbs(`<a href="#/runs">Runs</a> <span>/ ${escapeHtml(shortRun(runId))}</span>`);
  $("#view").innerHTML = `<p class="hint">Loading run…</p>`;
  let run, points, residuals;
  try {
    [run, points, residuals] = await Promise.all([
      api(`/api/runs/${encodeURIComponent(runId)}`),
      api(`/api/runs/${encodeURIComponent(runId)}/forecast-points?limit=2000`),
      api(`/api/runs/${encodeURIComponent(runId)}/residuals?limit=1000`),
    ]);
  } catch (error) {
    $("#view").innerHTML = `<div class="empty-state"><h2>Run not found</h2><p>${escapeHtml(error.message)}</p><p><a href="#/runs">Back to runs</a></p></div>`;
    return;
  }
  const series = [...new Set(points.map((point) => point.series_id).filter((s) => s !== null && s !== undefined))].map(String).sort();
  state.detail = { run, points, residuals, series, selectedSeries: "" };
  $("#topMeta").textContent = `captured ${formatDate(run.created_at)}`;

  const metricLookup = Object.fromEntries(
    (run.metrics || [])
      .filter((metric) => metric.slice_name === null)
      .map((metric) => [metric.metric_name, metric.metric_value])
  );
  const seriesSelector =
    series.length > 1
      ? `<select id="seriesFilter" aria-label="Filter chart by series">
           <option value="">All series (${series.length})</option>
           ${series.map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join("")}
         </select>`
      : "";
  $("#view").innerHTML = `
    <a class="back-link" href="#/runs">← Runs</a>
    <div class="detail-head">
      <h2>${escapeHtml(run.model_name || run.project_id || "Run detail")}</h2>
      <span class="run-id">${escapeHtml(run.run_id)}</span>
      <button type="button" class="copy-btn" id="copyRunId">copy</button>
      <span class="status ${escapeHtml(run.status || "")}">${escapeHtml((run.status || "").toUpperCase())}</span>
      <span class="meta"><a href="#/compare?base=${encodeURIComponent(run.run_id)}">Compare this run →</a></span>
    </div>
    <div class="summary-grid">
      ${metricCard("MAE", metricLookup.mae, "mean abs error")}
      ${metricCard("RMSE", metricLookup.rmse, "root mean sq error")}
      ${metricCard("WAPE", metricLookup.wape, "weighted abs pct error")}
      ${metricCard("Bias", metricLookup.bias, "mean error")}
      ${metricCard("Coverage", metricLookup.coverage, "interval hit rate")}
      ${metricCard("Points", run.points_count, `${fmt(run.series_count, 0)} series`, true)}
    </div>
    <div class="run-layout">
      <div class="run-main">
        <div class="panel">
          <div class="inspector-head">
            <span class="panel-title">Forecast inspector</span>
            ${seriesSelector}
            <div class="legend">
              <span class="l-forecast"><i></i>forecast</span>
              <span class="l-actual"><i></i>actual</span>
              <span class="l-benchmark"><i></i>benchmark</span>
              <span class="l-interval"><i></i>interval</span>
            </div>
          </div>
          <div id="chartGrid" class="chart-grid"></div>
          <div id="gridNote" class="grid-note" hidden></div>
        </div>
        <div class="tabs">
          ${tabButton("metrics", `Metrics (${(run.metrics || []).length})`)}
          ${tabButton("validation", `Validation (${(run.validation || []).length})`)}
          ${tabButton("residuals", "Residuals")}
          ${tabButton("artifacts", `Artifacts (${(run.artifacts || []).length})`)}
        </div>
        <div id="tabContent" class="tab-content"></div>
      </div>
      <aside class="run-rail">
        <div class="panel">
          <div class="panel-title" style="display:block;margin-bottom:10px">Run card</div>
          ${kv({
            Project: run.project_id,
            Model: run.model_name,
            Version: run.model_version,
            Adapter: run.adapter_name,
            Created: formatDate(run.created_at),
            Cutoff: formatRange(run.cutoff_start, run.cutoff_end),
            Target: formatRange(run.target_start, run.target_end),
            Series: fmt(run.series_count, 0),
            Points: fmt(run.points_count, 0),
            Validation: validationSummary(countBy(run.validation || [], "severity")),
            Trace: run.trace_id,
          })}
        </div>
        <div class="panel">
          <div class="panel-title" style="display:block;margin-bottom:10px">Trace timeline</div>
          ${traceTimeline(run.spans || [])}
        </div>
      </aside>
    </div>
  `;
  $("#copyRunId").addEventListener("click", async () => {
    let copied = false;
    try {
      await navigator.clipboard.writeText(run.run_id);
      copied = true;
    } catch {
      const scratch = document.createElement("textarea");
      scratch.value = run.run_id;
      scratch.style.position = "fixed";
      scratch.style.opacity = "0";
      document.body.appendChild(scratch);
      scratch.select();
      copied = document.execCommand("copy");
      scratch.remove();
    }
    const btn = $("#copyRunId");
    if (btn && copied) {
      btn.textContent = "copied";
      setTimeout(() => { const after = $("#copyRunId"); if (after) after.textContent = "copy"; }, 1200);
    }
  });
  const seriesFilter = $("#seriesFilter");
  if (seriesFilter) seriesFilter.addEventListener("change", (event) => changeSeries(event.target.value));
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.addEventListener("click", () => {
      state.runTab = button.dataset.tab;
      renderRunTab();
    });
  });
  renderCharts();
  renderRunTab();
}

async function changeSeries(seriesId) {
  const { run } = state.detail;
  state.detail.selectedSeries = seriesId;
  const query = seriesId ? `&series_id=${encodeURIComponent(seriesId)}` : "";
  const [points, residuals] = await Promise.all([
    api(`/api/runs/${encodeURIComponent(run.run_id)}/forecast-points?limit=2000${query}`),
    api(`/api/runs/${encodeURIComponent(run.run_id)}/residuals?limit=1000${query}`),
  ]);
  state.detail.points = points;
  state.detail.residuals = residuals;
  renderCharts();
  if (state.runTab === "residuals") renderRunTab();
}

function renderRunTab() {
  const { run, residuals } = state.detail;
  if (!["metrics", "validation", "residuals", "artifacts"].includes(state.runTab)) state.runTab = "metrics";
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.runTab);
  });
  const target = $("#tabContent");
  if (state.runTab === "metrics") {
    target.innerHTML = table(run.metrics || [], "No metrics computed for this run. Pass actuals to fops.capture() to enable evaluation.");
  } else if (state.runTab === "validation") {
    target.innerHTML = table(run.validation || [], "No validation issues. The captured forecast passed all checks.");
  } else if (state.runTab === "residuals") {
    target.innerHTML = table(residuals || [], "No residuals available. Residuals require actuals to be captured alongside the forecast.");
  } else if (state.runTab === "artifacts") {
    target.innerHTML = table(run.artifacts || [], "No artifacts recorded.");
  }
}

/* ---------- Projects ---------- */

function renderProjectsView() {
  setCrumbs("Projects");
  if (!state.runs.length) {
    $("#view").innerHTML = emptyStoreHtml();
    return;
  }
  const groups = new Map();
  state.runs.forEach((run) => {
    const key = run.project_id || "(none)";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(run);
  });
  const projects = [...groups.entries()].map(([project, runs]) => {
    const ordered = runs
      .slice()
      .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
    const latest = ordered[ordered.length - 1];
    const maeTrend = ordered.map((run) => run.mae).filter((v) => v !== null && v !== undefined).slice(-20);
    const statuses = countBy(runs, "validation_status");
    return { project, runs, ordered, latest, maeTrend, statuses };
  });
  projects.sort((a, b) => String(b.latest.created_at).localeCompare(String(a.latest.created_at)));
  $("#topMeta").textContent = `${projects.length} project${projects.length === 1 ? "" : "s"} · ${state.runs.length} run${state.runs.length === 1 ? "" : "s"}`;
  $("#view").innerHTML = `
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Project</th>
            <th class="num">Runs</th>
            <th>Models</th>
            <th>Last capture</th>
            <th class="num">Latest MAE</th>
            <th class="num">Latest WAPE</th>
            <th>MAE trend</th>
            <th>Validation</th>
          </tr>
        </thead>
        <tbody>
          ${projects
            .map(
              ({ project, runs, latest, maeTrend, statuses }) => `
            <tr data-href="#/runs?project=${encodeURIComponent(project)}">
              <td><span class="link">${escapeHtml(project)}</span></td>
              <td class="num">${runs.length}</td>
              <td>${escapeHtml([...new Set(runs.map((run) => run.model_name).filter(Boolean))].slice(0, 3).join(", ") || "–")}</td>
              <td>${escapeHtml(formatDate(latest.created_at))}</td>
              <td class="num">${fmt(latest.mae)}</td>
              <td class="num">${fmt(latest.wape)}</td>
              <td>${sparkline(maeTrend)}</td>
              <td>${["PASS", "WARN", "FAIL"]
                .filter((s) => statuses[s])
                .map((s) => `<span class="status ${s}">${statuses[s]} ${s}</span>`)
                .join(" · ") || "–"}</td>
            </tr>
          `
            )
            .join("")}
        </tbody>
      </table>
    </div>
    <p class="grid-note">MAE trend is oldest → newest capture. Click a project to see its runs.</p>
  `;
  attachRowLinks($("#view"));
}

function sparkline(values, width = 120, height = 26) {
  const clean = values.map(Number).filter(Number.isFinite);
  if (clean.length < 2) return `<span class="hint">–</span>`;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  const points = clean
    .map((value, index) => {
      const x = (index / (clean.length - 1)) * (width - 4) + 2;
      const y = height - 3 - ((value - min) / span) * (height - 6);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return `<svg class="spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="MAE trend"><polyline points="${points}"></polyline></svg>`;
}

/* ---------- Compare ---------- */

function renderCompareView(params) {
  setCrumbs("Compare");
  if (state.runs.length < 2) {
    $("#view").innerHTML = `<div class="empty-state"><h2>Need two runs to compare</h2><p>Capture at least two runs, then come back.</p></div>`;
    return;
  }
  const base = params.get("base") || state.runs[0].run_id;
  const candidate = params.get("candidate") || (state.runs.find((run) => run.run_id !== base) || {}).run_id;
  const option = (run, selected) =>
    `<option value="${escapeHtml(run.run_id)}" ${run.run_id === selected ? "selected" : ""}>${escapeHtml(
      [run.project_id, run.model_name, formatDate(run.created_at), shortRun(run.run_id)].filter(Boolean).join(" · ")
    )}</option>`;
  $("#view").innerHTML = `
    <div class="compare-controls">
      <label>Base
        <select id="baseSelect">${state.runs.map((run) => option(run, base)).join("")}</select>
      </label>
      <label>Candidate
        <select id="candidateSelect">${state.runs.map((run) => option(run, candidate)).join("")}</select>
      </label>
      <button type="button" id="compareButton">Compare</button>
    </div>
    <div id="compareResult" class="compare-result hint">Positive deltas on error metrics (MAE, RMSE, WAPE) mean the candidate got worse than the base.</div>
  `;
  const runCompare = async () => {
    const baseId = $("#baseSelect").value;
    const candidateId = $("#candidateSelect").value;
    const result = $("#compareResult");
    if (baseId === candidateId) {
      result.className = "compare-result hint";
      result.textContent = "Pick two different runs.";
      return;
    }
    window.history.replaceState(null, "", `#/compare?base=${encodeURIComponent(baseId)}&candidate=${encodeURIComponent(candidateId)}`);
    result.className = "compare-result";
    result.innerHTML = `<p class="hint">Comparing…</p>`;
    try {
      const diff = await api(
        `/api/diff?base_run_id=${encodeURIComponent(baseId)}&candidate_run_id=${encodeURIComponent(candidateId)}`
      );
      const regressions = diff.regressions || [];
      result.innerHTML = `
        <h4>${regressions.length ? `${regressions.length} regression${regressions.length === 1 ? "" : "s"} detected` : "No regressions detected"}</h4>
        ${regressions.length ? table(regressions, "") : ""}
        <h4>Metric deltas (candidate − base)</h4>
        ${table(diff.metric_deltas || [], "No overlapping metrics between the two runs.")}
        <h4>Forecast deltas${(diff.forecast_deltas || []).length >= 1000 ? " (first 1000)" : ""}</h4>
        ${table(
          (diff.forecast_deltas || [])
            .slice()
            .sort((a, b) =>
              String(a.series_id).localeCompare(String(b.series_id)) ||
              String(a.target_time).localeCompare(String(b.target_time))
            )
            .slice(0, 200),
          "No overlapping forecast points between the two runs."
        )}
      `;
    } catch (error) {
      result.innerHTML = `<p class="status FAIL">Compare failed: ${escapeHtml(error.message)}</p>`;
    }
  };
  $("#compareButton").addEventListener("click", runCompare);
  if (params.get("base") && params.get("candidate")) runCompare();
}

/* ---------- Forecast inspector charts ---------- */

function renderCharts() {
  const grid = $("#chartGrid");
  const note = $("#gridNote");
  if (!grid || !state.detail) return;
  const { points } = state.detail;
  const clean = points.filter(
    (point) =>
      point.yhat !== null &&
      point.yhat !== undefined &&
      Number.isFinite(new Date(point.target_time).getTime())
  );
  if (!clean.length) {
    grid.className = "chart-grid single";
    grid.innerHTML = `<div class="empty-state">No chartable points in this run.</div>`;
    note.hidden = true;
    return;
  }
  const groups = new Map();
  clean.forEach((point) => {
    const key = String(point.series_id ?? "");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(point);
  });
  groups.forEach((group) =>
    group.sort((a, b) => new Date(a.target_time).getTime() - new Date(b.target_time).getTime())
  );

  const entries = [...groups.entries()];
  const single = entries.length === 1;
  const shown = entries.slice(0, MAX_GRID_SERIES);
  grid.className = `chart-grid ${single ? "single" : ""}`;
  grid.innerHTML = shown
    .map(
      ([seriesId], index) => `
      <div class="chart-cell">
        <div class="chart-cell-head">
          <span class="series-name" title="${escapeHtml(seriesId)}">${escapeHtml(seriesId || "series")}</span>
          <span class="series-metric">${seriesMetricLabel(shown[index][1])}</span>
        </div>
        <div class="chart" data-index="${index}" style="height:${single ? 320 : 180}px"></div>
      </div>
    `
    )
    .join("");
  shown.forEach(([, group], index) => {
    drawSeriesChart(grid.querySelector(`.chart[data-index="${index}"]`), group, { compact: !single });
  });
  if (entries.length > MAX_GRID_SERIES) {
    note.hidden = false;
    note.textContent = `Showing ${MAX_GRID_SERIES} of ${entries.length} series — pick one from the series dropdown to inspect the rest.`;
  } else {
    note.hidden = true;
  }
}

function seriesMetricLabel(group) {
  const scored = group.filter((point) => point.actual !== null && point.actual !== undefined);
  if (!scored.length) return `${group.length} pts`;
  const absErr = scored.reduce((sum, point) => sum + Math.abs(Number(point.yhat) - Number(point.actual)), 0);
  const absActual = scored.reduce((sum, point) => sum + Math.abs(Number(point.actual)), 0);
  if (absActual > 0) return `WAPE ${(absErr / absActual).toFixed(3)}`;
  return `MAE ${(absErr / scored.length).toFixed(3)}`;
}

function drawSeriesChart(el, group, { compact = false } = {}) {
  if (!el) return;
  const width = el.clientWidth || 600;
  const height = el.clientHeight || (compact ? 180 : 320);
  const pad = { top: 8, right: 10, bottom: 20, left: 46 };
  const values = [];
  group.forEach((point) =>
    ["yhat", "actual", "benchmark_yhat", "yhat_lower", "yhat_upper"].forEach((key) => {
      if (point[key] !== null && point[key] !== undefined) values.push(Number(point[key]));
    })
  );
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const times = group.map((point) => new Date(point.target_time).getTime());
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const tSpan = tMax - tMin || 1;
  const x = (time) => pad.left + ((time - tMin) / tSpan) * innerW;
  const y = (value) => pad.top + innerH - ((value - min) / span) * innerH;
  const path = (key) => {
    let d = "";
    group.forEach((point) => {
      if (point[key] === null || point[key] === undefined) return;
      d += `${d ? "L" : "M"}${x(new Date(point.target_time).getTime()).toFixed(1)},${y(Number(point[key])).toFixed(1)}`;
    });
    return d;
  };

  const tickSteps = compact ? [0, 2, 4] : [0, 1, 2, 3, 4];
  const yTicks = tickSteps.map((i) => min + (span * i) / 4);
  const xTickTimes = tickSteps.map((i) => tMin + (tSpan * i) / 4);
  const gridLines = yTicks
    .map((tick) => `<line x1="${pad.left}" y1="${y(tick).toFixed(1)}" x2="${width - pad.right}" y2="${y(tick).toFixed(1)}" stroke="${COLORS.grid}"></line>`)
    .join("");
  const yLabels = yTicks
    .map((tick) => `<text x="${pad.left - 7}" y="${(y(tick) + 3).toFixed(1)}" text-anchor="end" font-size="9" fill="${COLORS.tick}" font-family="monospace">${escapeHtml(fmtTick(tick))}</text>`)
    .join("");
  const xLabels = xTickTimes
    .map((time, index) => {
      const anchor = index === 0 ? "start" : index === xTickTimes.length - 1 ? "end" : "middle";
      const tx = index === 0 ? pad.left : x(time);
      return `<text x="${tx.toFixed(1)}" y="${height - 6}" text-anchor="${anchor}" font-size="9" fill="${COLORS.tick}" font-family="monospace">${escapeHtml(formatTickDate(time))}</text>`;
    })
    .join("");

  el.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="Forecast versus actual chart">
      ${gridLines}
      <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="${COLORS.axis}"></line>
      ${intervalBand(group, x, y)}
      <path d="${path("benchmark_yhat")}" fill="none" stroke="${COLORS.benchmark}" stroke-width="1" stroke-dasharray="4 4"></path>
      <path d="${path("actual")}" fill="none" stroke="${COLORS.actual}" stroke-width="1.4"></path>
      <path d="${path("yhat")}" fill="none" stroke="${COLORS.forecast}" stroke-width="1.6"></path>
      <line class="chart-guide" y1="${pad.top}" y2="${height - pad.bottom}" stroke="${COLORS.guide}" stroke-width="1" stroke-dasharray="2 3" visibility="hidden"></line>
      ${yLabels}
      ${xLabels}
    </svg>
    <div class="chart-tooltip"></div>
  `;
  attachChartTooltip(el, group, { x, pad, innerW, tMin, tSpan });
}

function attachChartTooltip(el, group, geometry) {
  const tooltip = el.querySelector(".chart-tooltip");
  const guide = el.querySelector(".chart-guide");
  el.onmousemove = (event) => {
    const rect = el.getBoundingClientRect();
    const mx = event.clientX - rect.left;
    const ratio = (mx - geometry.pad.left) / geometry.innerW;
    if (ratio < -0.02 || ratio > 1.02) {
      tooltip.style.display = "none";
      guide.setAttribute("visibility", "hidden");
      return;
    }
    const targetTime = geometry.tMin + Math.max(0, Math.min(1, ratio)) * geometry.tSpan;
    let nearest = group[0];
    let bestDistance = Infinity;
    group.forEach((point) => {
      const distance = Math.abs(new Date(point.target_time).getTime() - targetTime);
      if (distance < bestDistance) {
        bestDistance = distance;
        nearest = point;
      }
    });
    const px = geometry.x(new Date(nearest.target_time).getTime());
    guide.setAttribute("x1", px);
    guide.setAttribute("x2", px);
    guide.setAttribute("visibility", "visible");
    const body = [
      ["forecast", "yhat"],
      ["actual", "actual"],
      ["benchmark", "benchmark_yhat"],
      ["lower", "yhat_lower"],
      ["upper", "yhat_upper"],
    ]
      .filter(([, key]) => nearest[key] !== null && nearest[key] !== undefined)
      .map(([label, key]) => `<div><span>${label}</span><strong>${fmt(nearest[key])}</strong></div>`)
      .join("");
    tooltip.innerHTML = `<div><strong>${escapeHtml(formatDate(nearest.target_time))}</strong></div>${body}`;
    tooltip.style.display = "block";
    tooltip.style.left = `${Math.min(px + 12, rect.width - tooltip.offsetWidth - 4)}px`;
    tooltip.style.top = `${Math.max(2, event.clientY - rect.top - tooltip.offsetHeight - 10)}px`;
  };
  el.onmouseleave = () => {
    tooltip.style.display = "none";
    guide.setAttribute("visibility", "hidden");
  };
}

function intervalBand(points, x, y) {
  const usable = points.filter((point) => point.yhat_lower !== null && point.yhat_upper !== null);
  if (!usable.length) return "";
  const px = (point) => x(new Date(point.target_time).getTime()).toFixed(1);
  const top = usable.map((point, index) => `${index ? "L" : "M"}${px(point)},${y(Number(point.yhat_upper)).toFixed(1)}`).join("");
  const bottom = usable
    .slice()
    .reverse()
    .map((point) => `L${px(point)},${y(Number(point.yhat_lower)).toFixed(1)}`)
    .join("");
  return `<path d="${top}${bottom}Z" fill="${COLORS.band}"></path>`;
}

/* ---------- Shared rendering helpers ---------- */

function metricCard(label, value, caption = "", neutral = false) {
  const digits = neutral ? 0 : 3;
  return `<div class="metric-card ${neutral ? "neutral" : ""}"><span>${escapeHtml(label)}</span><strong>${fmt(value, digits)}</strong>${
    caption ? `<small>${escapeHtml(caption)}</small>` : ""
  }</div>`;
}

function tabButton(tab, label) {
  return `<button type="button" data-tab="${tab}" class="${state.runTab === tab ? "active" : ""}">${label}</button>`;
}

function table(rows, emptyMessage = "No rows.") {
  if (!rows.length) return `<p class="empty-state">${escapeHtml(emptyMessage)}</p>`;
  const columns = Object.keys(rows[0]).filter((column) => !["metadata_json", "sample_json", "schema_json"].includes(column));
  const header = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${columns.map((column) => `<td>${cell(column, row[column])}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="table-wrap"><table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function cell(column, value) {
  if (column === "severity" || column === "validation_status" || column === "status") {
    return `<span class="status ${escapeHtml(String(value ?? ""))}">${escapeHtml(formatCell(value))}</span>`;
  }
  if (column === "delta" && Number.isFinite(Number(value)) && Number(value) !== 0) {
    const direction = Number(value) > 0 ? "delta-up" : "delta-down";
    return `<span class="${direction}">${Number(value) > 0 ? "+" : ""}${fmt(value)}</span>`;
  }
  return escapeHtml(formatCell(value));
}

function kv(values) {
  return `<dl class="kv">${Object.entries(values)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(formatCell(value))}</dd>`)
    .join("")}</dl>`;
}

function countBy(rows, key) {
  return rows.reduce((counts, row) => {
    const value = row[key] || "unknown";
    counts[value] = (counts[value] || 0) + 1;
    return counts;
  }, {});
}

function validationSummary(counts) {
  const parts = Object.entries(counts).map(([severity, count]) => `${count} ${severity}`);
  return parts.length ? parts.join(", ") : "clean";
}

function traceTimeline(spans) {
  if (!spans.length) return `<p class="hint">No local spans recorded.</p>`;
  const max = Math.max(...spans.map((span) => Number(span.duration_ms || 0)), 1);
  return `<div class="trace">${spans
    .map((span) => {
      const width = Math.max(2, (Number(span.duration_ms || 0) / max) * 100);
      return `<div class="trace-row"><span title="${escapeHtml(span.span_name)}">${escapeHtml(span.span_name)}</span><span><span class="trace-bar" style="display:block;width:${width}%"></span></span><span>${fmt(span.duration_ms, 1)}ms</span></div>`;
    })
    .join("")}</div>`;
}

function shortRun(runId) {
  if (!runId) return "";
  return runId.length > 28 ? `${runId.slice(0, 14)}…${runId.slice(-8)}` : runId;
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTickDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatRange(start, end) {
  if (!start && !end) return "";
  if (start === end || !end) return formatDate(start);
  return `${formatDate(start)} → ${formatDate(end)}`;
}

function fmtTick(value) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `${(value / 1000).toFixed(1)}k`;
  if (abs >= 100) return value.toFixed(0);
  return value.toFixed(2);
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

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.detail && $("#chartGrid")) renderCharts();
  }, 150);
});

boot().catch((error) => {
  document.body.innerHTML = `<main style="padding:24px"><div class="empty-state"><h2>ForecastOps could not load</h2><p>${escapeHtml(error.message)}</p></div></main>`;
});
