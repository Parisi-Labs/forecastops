const state = {
  runs: [],
  selectedRunId: null,
  activeTab: "metrics",
  sort: { key: "created_at", dir: "desc" },
  detail: null, // { run, points, residuals, series, selectedSeries }
};

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

async function boot() {
  const health = await api("/api/health");
  $("#storeInfo").textContent = health.store;
  $("#storeInfo").title = `Store: ${health.store}`;
  $("#refreshButton").addEventListener("click", refresh);
  $("#projectFilter").addEventListener("change", renderRuns);
  $("#statusFilter").addEventListener("change", renderRuns);
  $("#searchFilter").addEventListener("input", renderRuns);
  document.querySelectorAll("#runsTable th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sort.key === key) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort = { key, dir: key === "created_at" ? "desc" : "asc" };
      }
      renderRuns();
    });
  });
  await refresh();
}

async function refresh() {
  state.runs = await api("/api/runs");
  renderFilters();
  renderRuns();
  if (!state.runs.length) {
    renderNoRuns();
    return;
  }
  const stillExists = state.runs.some((run) => run.run_id === state.selectedRunId);
  if (!stillExists) state.selectedRunId = null;
  if (!state.selectedRunId) await selectRun(state.runs[0].run_id);
}

function renderNoRuns() {
  $("#detail").innerHTML = `
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
      <p class="hint">Runs are stored locally in the store shown in the header. Nothing leaves this machine.</p>
    </div>
  `;
}

function renderFilters() {
  const select = $("#projectFilter");
  const current = select.value;
  const projects = [...new Set(state.runs.map((run) => run.project_id).filter(Boolean))].sort();
  select.innerHTML = `<option value="">All projects</option>${projects
    .map((project) => `<option value="${escapeHtml(project)}">${escapeHtml(project)}</option>`)
    .join("")}`;
  select.value = projects.includes(current) ? current : "";
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

function renderRuns() {
  const rows = sortedRuns(filteredRuns());
  $("#runCount").textContent = `${rows.length} of ${state.runs.length} runs`;
  document.querySelectorAll("#runsTable th[data-sort]").forEach((th) => {
    const active = th.dataset.sort === state.sort.key;
    th.classList.toggle("sorted", active);
    const base = th.textContent.replace(/ [↑↓]$/, "");
    th.textContent = active ? `${base} ${state.sort.dir === "asc" ? "↑" : "↓"}` : base;
  });
  const tbody = $("#runsTable tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="13" style="color:var(--muted)">No runs match the current filters.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map(
      (run) => `
      <tr data-run-id="${escapeHtml(run.run_id)}" class="${run.run_id === state.selectedRunId ? "selected" : ""}">
        <td title="${escapeHtml(run.run_id)}">${escapeHtml(shortRun(run.run_id))}</td>
        <td>${escapeHtml(run.project_id || "–")}</td>
        <td>${escapeHtml(run.model_name || "–")}</td>
        <td>${escapeHtml(run.adapter_name || "–")}</td>
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
  tbody.querySelectorAll("tr[data-run-id]").forEach((row) => {
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
  const series = [...new Set(points.map((point) => point.series_id).filter((s) => s !== null && s !== undefined))].map(String).sort();
  state.detail = { run, points, residuals, series, selectedSeries: "" };
  renderDetail();
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
  drawForecastChart($("#forecastChart"), points);
  if (state.activeTab === "residuals") renderTab();
}

function renderDetail() {
  const { run, points, series, selectedSeries } = state.detail;
  const metricLookup = Object.fromEntries(
    (run.metrics || [])
      .filter((metric) => metric.slice_name === null)
      .map((metric) => [metric.metric_name, metric.metric_value])
  );
  const validationCounts = countBy(run.validation || [], "severity");
  const seriesSelector =
    series.length > 1
      ? `<label for="seriesFilter">Series</label>
         <select id="seriesFilter">
           <option value="">All (${series.length})</option>
           ${series.map((s) => `<option value="${escapeHtml(s)}" ${s === selectedSeries ? "selected" : ""}>${escapeHtml(s)}</option>`).join("")}
         </select>`
      : "";
  $("#detail").innerHTML = `
    <div class="detail-head">
      <h2>${escapeHtml(run.model_name || run.project_id || "Run detail")}</h2>
      <span class="run-id">${escapeHtml(run.run_id)}</span>
      <button type="button" class="copy-btn" id="copyRunId">Copy ID</button>
      <span class="status ${escapeHtml(run.status || "")}">${escapeHtml((run.status || "").toUpperCase())}</span>
    </div>
    <div class="summary-grid">
      ${metricCard("MAE", metricLookup.mae)}
      ${metricCard("RMSE", metricLookup.rmse)}
      ${metricCard("WAPE", metricLookup.wape)}
      ${metricCard("Bias", metricLookup.bias)}
      ${metricCard("Coverage", metricLookup.coverage)}
      ${metricCard("Points", run.points_count, 0)}
    </div>
    <div class="detail-grid">
      <div>
        <div class="chart-panel">
          <div class="panel-toolbar">${seriesSelector}</div>
          <div id="forecastChart" class="chart"></div>
          <div class="legend">
            <span class="l-forecast"><i></i>forecast</span>
            <span class="l-actual"><i></i>actual</span>
            <span class="l-benchmark"><i></i>benchmark</span>
            <span class="l-interval"><i></i>interval</span>
          </div>
        </div>
        <div class="tabs">
          ${tabButton("metrics", `Metrics (${(run.metrics || []).length})`)}
          ${tabButton("validation", `Validation (${(run.validation || []).length})`)}
          ${tabButton("residuals", "Residuals")}
          ${tabButton("artifacts", `Artifacts (${(run.artifacts || []).length})`)}
          ${tabButton("compare", "Compare")}
        </div>
        <div id="tabContent" class="tab-content"></div>
      </div>
      <div class="panel">
        <h3>Run details</h3>
        ${kv({
          Project: run.project_id,
          Model: run.model_name,
          Version: run.model_version,
          Adapter: run.adapter_name,
          Created: formatDate(run.created_at),
          Cutoff: formatRange(run.cutoff_start, run.cutoff_end),
          Target: formatRange(run.target_start, run.target_end),
          Series: run.series_count,
          Points: run.points_count,
          Validation: validationSummary(validationCounts),
          Trace: run.trace_id,
        })}
        <h3 style="margin-top:18px">Trace timeline</h3>
        ${traceTimeline(run.spans || [])}
      </div>
    </div>
  `;
  $("#copyRunId").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(run.run_id);
      $("#copyRunId").textContent = "Copied";
      setTimeout(() => { const btn = $("#copyRunId"); if (btn) btn.textContent = "Copy ID"; }, 1200);
    } catch {
      /* clipboard unavailable */
    }
  });
  const seriesFilter = $("#seriesFilter");
  if (seriesFilter) seriesFilter.addEventListener("change", (event) => changeSeries(event.target.value));
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeTab = button.dataset.tab;
      renderTab();
    });
  });
  drawForecastChart($("#forecastChart"), points);
  renderTab();
}

function renderTab() {
  const { run, residuals } = state.detail;
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.activeTab);
  });
  const target = $("#tabContent");
  if (state.activeTab === "metrics") {
    target.innerHTML = table(run.metrics || [], "No metrics computed for this run. Pass actuals to fops.capture() to enable evaluation.");
  } else if (state.activeTab === "validation") {
    target.innerHTML = table(run.validation || [], "No validation issues. The captured forecast passed all checks.");
  } else if (state.activeTab === "residuals") {
    target.innerHTML = table(residuals || [], "No residuals available. Residuals require actuals to be captured alongside the forecast.");
  } else if (state.activeTab === "artifacts") {
    target.innerHTML = table(run.artifacts || [], "No artifacts recorded.");
  } else if (state.activeTab === "compare") {
    renderCompareTab(target);
  }
}

function renderCompareTab(target) {
  const { run } = state.detail;
  const candidates = state.runs.filter((other) => other.run_id !== run.run_id);
  if (!candidates.length) {
    target.innerHTML = `<p class="empty-state">Capture a second run to compare against this one.</p>`;
    return;
  }
  const sameProject = candidates.filter((other) => other.project_id === run.project_id);
  const otherProjects = candidates.filter((other) => other.project_id !== run.project_id);
  const option = (other) =>
    `<option value="${escapeHtml(other.run_id)}">${escapeHtml(
      [other.project_id, other.model_name, formatDate(other.created_at), shortRun(other.run_id)].filter(Boolean).join(" · ")
    )}</option>`;
  target.innerHTML = `
    <div class="compare-controls">
      <label for="compareSelect">Compare this run (base) against</label>
      <select id="compareSelect">
        ${sameProject.length ? `<optgroup label="Same project">${sameProject.map(option).join("")}</optgroup>` : ""}
        ${otherProjects.length ? `<optgroup label="Other projects">${otherProjects.map(option).join("")}</optgroup>` : ""}
      </select>
      <button type="button" class="secondary" id="compareButton">Compare</button>
    </div>
    <div id="compareResult" class="compare-result hint">Pick a candidate run, then compare. Positive deltas on error metrics (MAE, RMSE, WAPE) mean the candidate got worse.</div>
  `;
  $("#compareButton").addEventListener("click", async () => {
    const candidateId = $("#compareSelect").value;
    const result = $("#compareResult");
    result.className = "compare-result";
    result.innerHTML = `<p class="hint">Comparing…</p>`;
    try {
      const diff = await api(
        `/api/diff?base_run_id=${encodeURIComponent(run.run_id)}&candidate_run_id=${encodeURIComponent(candidateId)}`
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
  });
}

function drawForecastChart(el, points) {
  if (!el) return;
  const clean = points.filter(
    (point) =>
      point.yhat !== null &&
      point.yhat !== undefined &&
      Number.isFinite(new Date(point.target_time).getTime())
  );
  if (!clean.length) {
    el.innerHTML = `<div class="empty-state">No chartable points in this run.</div>`;
    return;
  }
  const width = el.clientWidth || 900;
  const height = el.clientHeight || 340;
  const pad = { top: 12, right: 16, bottom: 26, left: 56 };
  const values = [];
  clean.forEach((point) =>
    ["yhat", "actual", "benchmark_yhat", "yhat_lower", "yhat_upper"].forEach((key) => {
      if (point[key] !== null && point[key] !== undefined) values.push(Number(point[key]));
    })
  );
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const times = clean.map((point) => new Date(point.target_time).getTime());
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const tSpan = tMax - tMin || 1;
  const x = (time) => pad.left + ((time - tMin) / tSpan) * innerW;
  const y = (value) => pad.top + innerH - ((value - min) / span) * innerH;

  // One polyline per series so multi-series runs do not get stitched into a single line.
  const groups = new Map();
  clean.forEach((point) => {
    const key = String(point.series_id ?? "");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(point);
  });
  groups.forEach((group) =>
    group.sort((a, b) => new Date(a.target_time).getTime() - new Date(b.target_time).getTime())
  );

  const path = (group, key) => {
    let d = "";
    group.forEach((point) => {
      if (point[key] === null || point[key] === undefined) return;
      d += `${d ? "L" : "M"}${x(new Date(point.target_time).getTime()).toFixed(1)},${y(Number(point[key])).toFixed(1)}`;
    });
    return d;
  };
  const lines = [...groups.values()]
    .map(
      (group) => `
      ${intervalBand(group, x, y)}
      <path d="${path(group, "benchmark_yhat")}" fill="none" stroke="#9b9b9b" stroke-width="1.5" stroke-dasharray="5 4"></path>
      <path d="${path(group, "actual")}" fill="none" stroke="#111111" stroke-width="1.8"></path>
      <path d="${path(group, "yhat")}" fill="none" stroke="#2563eb" stroke-width="2"></path>
    `
    )
    .join("");

  const yTicks = [0, 1, 2, 3, 4].map((i) => min + (span * i) / 4);
  const xTickTimes = [...new Set([0, 1, 2, 3, 4].map((i) => tMin + (tSpan * i) / 4))];
  const gridLines = yTicks
    .map((tick) => `<line x1="${pad.left}" y1="${y(tick).toFixed(1)}" x2="${width - pad.right}" y2="${y(tick).toFixed(1)}" stroke="#f0f0f0"></line>`)
    .join("");
  const yLabels = yTicks
    .map((tick) => `<text x="${pad.left - 8}" y="${(y(tick) + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="#9b9b9b" font-family="monospace">${escapeHtml(fmtTick(tick))}</text>`)
    .join("");
  const xLabels = xTickTimes
    .map((time) => `<text x="${x(time).toFixed(1)}" y="${height - 8}" text-anchor="middle" font-size="10" fill="#9b9b9b" font-family="monospace">${escapeHtml(formatTickDate(time))}</text>`)
    .join("");

  el.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="Forecast versus actual chart">
      ${gridLines}
      <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#e4e4e4"></line>
      <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}" stroke="#e4e4e4"></line>
      ${lines}
      <line id="chartGuide" y1="${pad.top}" y2="${height - pad.bottom}" stroke="#111" stroke-width="1" stroke-dasharray="2 3" visibility="hidden"></line>
      ${yLabels}
      ${xLabels}
    </svg>
    <div class="chart-tooltip" id="chartTooltip"></div>
  `;
  attachChartTooltip(el, groups, { x, pad, width, innerW, tMin, tSpan });
}

function attachChartTooltip(el, groups, geometry) {
  const tooltip = el.querySelector("#chartTooltip");
  const guide = el.querySelector("#chartGuide");
  const multi = groups.size > 1;
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
    // Nearest point per series at the hovered time.
    const nearest = [...groups.entries()].map(([seriesId, group]) => {
      let best = group[0];
      let bestDistance = Infinity;
      group.forEach((point) => {
        const distance = Math.abs(new Date(point.target_time).getTime() - targetTime);
        if (distance < bestDistance) {
          bestDistance = distance;
          best = point;
        }
      });
      return [seriesId, best];
    });
    const anchor = nearest[0][1];
    const px = geometry.x(new Date(anchor.target_time).getTime());
    guide.setAttribute("x1", px);
    guide.setAttribute("x2", px);
    guide.setAttribute("visibility", "visible");
    let body;
    if (multi) {
      body = nearest
        .slice(0, 8)
        .map(
          ([seriesId, point]) =>
            `<div><span>${escapeHtml(seriesId)}</span><strong>${fmt(point.yhat)}${
              point.actual !== null && point.actual !== undefined ? ` / ${fmt(point.actual)}` : ""
            }</strong></div>`
        )
        .join("");
      if (nearest.length > 8) body += `<div><span>… ${nearest.length - 8} more series</span></div>`;
      body = `<div><span>series</span><strong>forecast / actual</strong></div>${body}`;
    } else {
      body = [
        ["forecast", "yhat"],
        ["actual", "actual"],
        ["benchmark", "benchmark_yhat"],
        ["lower", "yhat_lower"],
        ["upper", "yhat_upper"],
      ]
        .filter(([, key]) => anchor[key] !== null && anchor[key] !== undefined)
        .map(([label, key]) => `<div><span>${label}</span><strong>${fmt(anchor[key])}</strong></div>`)
        .join("");
    }
    tooltip.innerHTML = `<div><strong>${escapeHtml(formatDate(anchor.target_time))}</strong></div>${body}`;
    tooltip.style.display = "block";
    tooltip.style.left = `${Math.min(px + 12, rect.width - tooltip.offsetWidth - 4)}px`;
    tooltip.style.top = `${Math.max(4, event.clientY - rect.top - tooltip.offsetHeight - 10)}px`;
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
  return `<path d="${top}${bottom}Z" fill="rgba(37, 99, 235, .1)"></path>`;
}

function metricCard(label, value, digits = 3) {
  return `<div class="metric-card"><span>${escapeHtml(label)}</span><strong>${fmt(value, digits)}</strong></div>`;
}

function tabButton(tab, label) {
  return `<button type="button" data-tab="${tab}" class="${state.activeTab === tab ? "active" : ""}">${label}</button>`;
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
    if (state.detail) drawForecastChart($("#forecastChart"), state.detail.points);
  }, 150);
});

boot().catch((error) => {
  document.body.innerHTML = `<main style="padding:24px"><div class="empty-state"><h2>ForecastOps could not load</h2><p>${escapeHtml(error.message)}</p></div></main>`;
});
