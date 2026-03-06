/* Kiln — LLMOps Pipeline Manager */
/* globals */

// API URL detection:
// - In Perplexity deployment: port/8000 gets replaced with the proxy path
// - In Docker/standalone: the literal string remains, so we fall back to same-origin
const _PROXY_URL = "port/8000";

function resolveApiBase(rawBase) {
  const value = (rawBase || "").trim();
  if (!value || value === "port/8000" || value.includes("PORT_8000")) {
    return "";
  }
  if (value.startsWith("http://") || value.startsWith("https://")) {
    return value.replace(/\/+$/, "");
  }
  if (value.startsWith("/")) {
    return value.replace(/\/+$/, "");
  }
  return "";
}

const API = resolveApiBase(window.__KILN_API_BASE__ || _PROXY_URL);

let currentView = "dashboard";
let dashboardData = null;
let modelsData = [];
let runsData = [];
let incidentsData = [];
let currentRunDetail = null;

/* ===== Theme ===== */

let theme = window.matchMedia("(prefers-color-scheme: dark)").matches
  ? "dark"
  : "light";
document.documentElement.setAttribute("data-theme", theme);

function toggleTheme() {
  theme = theme === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.querySelector("[data-theme-toggle]");
  if (btn) {
    btn.innerHTML =
      theme === "dark"
        ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>'
        : '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
    btn.setAttribute(
      "aria-label",
      `Switch to ${theme === "dark" ? "light" : "dark"} mode`
    );
  }
}

/* ===== Navigation ===== */

function navigate(view, data) {
  currentView = view;

  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.view === view);
  });

  const titles = {
    dashboard: "Dashboard",
    models: "Models",
    runs: "Pipeline Runs",
    incidents: "Incidents",
    about: "About Kiln",
    "run-detail": "Run Details",
    "model-detail": "Model Details",
  };
  document.getElementById("header-title").textContent =
    titles[view] || "Dashboard";

  renderView(view, data);
}

function renderView(view, data) {
  const main = document.getElementById("main-content");

  switch (view) {
    case "dashboard":
      renderDashboard(main);
      break;
    case "models":
      renderModels(main);
      break;
    case "runs":
      renderRuns(main);
      break;
    case "incidents":
      renderIncidents(main);
      break;
    case "about":
      renderAbout(main);
      break;
    case "run-detail":
      renderRunDetail(main, data);
      break;
    case "model-detail":
      renderModelDetail(main, data);
      break;
    default:
      renderDashboard(main);
  }
}

/* ===== API ===== */

async function apiFetch(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return sanitizeData(await res.json());
}

async function apiPost(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return sanitizeData(await res.json());
}

async function apiFetchText(path) {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.text();
}

/* ===== Helpers ===== */

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function sanitizeData(value) {
  if (typeof value === "string") {
    return escapeHtml(value);
  }
  if (Array.isArray(value)) {
    return value.map(sanitizeData);
  }
  if (value && typeof value === "object") {
    const sanitized = {};
    Object.keys(value).forEach((key) => {
      sanitized[key] = sanitizeData(value[key]);
    });
    return sanitized;
  }
  return value;
}

function downloadTextFile(filename, content) {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function timeAgo(dateStr) {
  if (!dateStr) {
    return "—";
  }
  const date = new Date(dateStr);
  const now = new Date();
  const diff = Math.floor((now - date) / 1000);

  if (diff < 60) {
    return "just now";
  }
  if (diff < 3600) {
    return `${Math.floor(diff / 60)}m ago`;
  }
  if (diff < 86400) {
    return `${Math.floor(diff / 3600)}h ago`;
  }
  if (diff < 604800) {
    return `${Math.floor(diff / 86400)}d ago`;
  }
  return date.toLocaleDateString();
}

function formatDuration(seconds) {
  if (!seconds) {
    return "—";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  }
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function badgeHTML(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

function stageIcon(key) {
  const icons = {
    benchmarks: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/></svg>',
    safety: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    documentation: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    packaging: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>',
    serving: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/></svg>',
    monitoring: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>',
    incidents: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>',
    improvement: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>',
  };
  return icons[key] || "";
}

/* ===== Dashboard View ===== */

async function renderDashboard(container) {
  container.innerHTML =
    '<div style="padding:var(--space-12);text-align:center;color:var(--color-text-faint)">Loading...</div>';

  try {
    dashboardData = await apiFetch("/api/dashboard");
  } catch {
    container.innerHTML =
      '<div class="empty-state"><h3>Cannot connect to API</h3><p>Make sure the backend is running.</p></div>';
    return;
  }

  const s = dashboardData.stats;

  container.innerHTML = `
    <div class="kpi-grid animate-in">
      <div class="kpi-card">
        <div class="kpi-label">Models</div>
        <div class="kpi-value">${s.total_models}</div>
        <div class="kpi-delta neutral">Registered</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Pipeline Runs</div>
        <div class="kpi-value">${s.total_runs}</div>
        <div class="kpi-delta positive">${s.pass_rate}% pass rate</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Passed</div>
        <div class="kpi-value" style="color:var(--color-success)">${s.passed_runs}</div>
        <div class="kpi-delta positive">${s.passed_runs > 0 ? "Completed" : "None yet"}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Failed</div>
        <div class="kpi-value" style="color:${s.failed_runs > 0 ? "var(--color-error)" : "var(--color-text-faint)"}">${s.failed_runs}</div>
        <div class="kpi-delta ${s.failed_runs > 0 ? "negative" : "neutral"}">${s.failed_runs > 0 ? "Needs attention" : "None"}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Open Incidents</div>
        <div class="kpi-value" style="color:${s.open_incidents > 0 ? "var(--color-error)" : "var(--color-success)"}">${s.open_incidents}</div>
        <div class="kpi-delta ${s.open_incidents > 0 ? "negative" : "positive"}">${s.open_incidents > 0 ? "Active" : "All clear"}</div>
      </div>
    </div>

    <div class="content-grid">
      <div class="card animate-in full-width" id="latest-pipeline-card">
        <div class="card-header">
          <div>
            <div class="card-title">Latest Pipeline</div>
            <div class="card-subtitle">Most recent pipeline run</div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="navigate('runs')">View All</button>
        </div>
        <div id="latest-pipeline-content">Loading...</div>
      </div>

      <div class="card animate-in">
        <div class="card-header">
          <div>
            <div class="card-title">Recent Models</div>
            <div class="card-subtitle">${s.total_models} registered</div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="navigate('models')">View All</button>
        </div>
        <div class="table-wrapper">
          <table>
            <thead><tr><th>Model</th><th>Params</th><th>Status</th></tr></thead>
            <tbody>
              ${dashboardData.models
                .map(
                  (m) => `
                <tr style="cursor:pointer" onclick="navigate('model-detail', ${m.id})">
                  <td><strong>${m.name}</strong></td>
                  <td class="mono">${m.parameters || "—"}</td>
                  <td>${badgeHTML(m.status)}</td>
                </tr>
              `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card animate-in">
        <div class="card-header">
          <div>
            <div class="card-title">Activity</div>
            <div class="card-subtitle">Recent events</div>
          </div>
        </div>
        <ul class="activity-feed">
          ${dashboardData.recent_activity
            .slice(0, 8)
            .map(
              (a) => `
            <li class="activity-item">
              <div class="activity-dot ${a.event_type}"></div>
              <span class="activity-text">${a.message}</span>
              <span class="activity-time">${timeAgo(a.created_at)}</span>
            </li>
          `
            )
            .join("")}
        </ul>
      </div>
    </div>
  `;

  loadLatestPipeline();
}

async function loadLatestPipeline() {
  const content = document.getElementById("latest-pipeline-content");
  if (!content) {
    return;
  }

  try {
    const runs = await apiFetch("/api/runs");
    if (runs.length === 0) {
      content.innerHTML =
        '<div class="empty-state"><p>No pipeline runs yet. Start one to see results.</p></div>';
      return;
    }

    const latestRun = runs[0];
    const runDetail = await apiFetch(`/api/runs/${latestRun.id}`);

    content.innerHTML = `
      <div style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:var(--space-3)">
        <strong>${runDetail.model_name}</strong>
        ${badgeHTML(runDetail.status)}
        <span class="mono" style="color:var(--color-text-faint);font-size:var(--text-xs)">Run #${runDetail.id} · ${timeAgo(runDetail.created_at)}</span>
      </div>
      <div class="pipeline-flow">
        ${runDetail.stages
          .map(
            (s) => `
          <div class="pipeline-stage ${s.status}" onclick="navigate('run-detail', ${runDetail.id})" title="${s.stage_name}: ${s.status}">
            <div class="stage-icon">${stageIcon(s.stage_key)}</div>
            <span class="stage-label">${s.stage_name.replace(" & ", " &amp; ")}</span>
            <span class="stage-duration">${formatDuration(s.duration_seconds)}</span>
          </div>
        `
          )
          .join("")}
      </div>
    `;
  } catch {
    content.innerHTML =
      '<div style="color:var(--color-text-faint);font-size:var(--text-sm)">Could not load pipeline data.</div>';
  }
}

/* ===== Models View ===== */

async function renderModels(container) {
  container.innerHTML =
    '<div style="padding:var(--space-12);text-align:center;color:var(--color-text-faint)">Loading...</div>';

  try {
    modelsData = await apiFetch("/api/models");
  } catch {
    container.innerHTML =
      '<div class="empty-state"><h3>Cannot load models</h3></div>';
    return;
  }

  if (modelsData.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
        <h3>No models yet</h3>
        <p>Register your first model to start running evaluations.</p>
        <button class="btn btn-primary" style="margin-top:var(--space-4)" onclick="openNewModelModal()">Register Model</button>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-5)">
      <div style="font-size:var(--text-sm);color:var(--color-text-muted)">${modelsData.length} models registered</div>
      <button class="btn btn-primary btn-sm" onclick="openNewModelModal()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5v14"/></svg>
        Register Model
      </button>
    </div>
    <div class="card">
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th>Parameters</th>
              <th>Architecture</th>
              <th>Status</th>
              <th>Runs</th>
              <th>Last Run</th>
              <th>Registered</th>
            </tr>
          </thead>
          <tbody>
            ${modelsData
              .map(
                (m) => `
              <tr style="cursor:pointer" onclick="navigate('model-detail', ${m.id})">
                <td>
                  <div><strong>${m.name}</strong></div>
                  ${m.repo_id ? `<div class="mono" style="font-size:var(--text-xs);color:var(--color-text-faint)">${m.repo_id}</div>` : ""}
                </td>
                <td class="mono">${m.parameters || "—"}</td>
                <td style="font-size:var(--text-xs);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${m.architecture || "—"}</td>
                <td>${badgeHTML(m.status)}</td>
                <td class="mono">${m.run_count}</td>
                <td style="font-size:var(--text-xs)">${m.latest_run ? `${badgeHTML(m.latest_run.status)}` : "—"}</td>
                <td style="font-size:var(--text-xs);color:var(--color-text-faint)">${timeAgo(m.created_at)}</td>
              </tr>
            `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

/* ===== Model Detail View ===== */

async function renderModelDetail(container, modelId) {
  container.innerHTML =
    '<div style="padding:var(--space-12);text-align:center;color:var(--color-text-faint)">Loading...</div>';

  let model;
  try {
    model = await apiFetch(`/api/models/${modelId}`);
  } catch {
    container.innerHTML =
      '<div class="empty-state"><h3>Model not found</h3></div>';
    return;
  }

  document.getElementById("header-title").textContent = model.name;

  container.innerHTML = `
    <div class="model-header animate-in">
      <div class="model-info">
        <div class="model-name">${model.name}</div>
        ${model.repo_id ? `<a class="model-repo" href="https://huggingface.co/${model.repo_id}" target="_blank" rel="noopener noreferrer">${model.repo_id}</a>` : ""}
        <div class="model-meta-row">
          ${model.parameters ? `<span class="model-meta-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/></svg>${model.parameters} params</span>` : ""}
          ${model.architecture ? `<span class="model-meta-tag"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/></svg>${model.architecture}</span>` : ""}
          <span class="model-meta-tag">${badgeHTML(model.status)}</span>
        </div>
        ${model.description ? `<p style="margin-top:var(--space-3);font-size:var(--text-sm);color:var(--color-text-muted);max-width:70ch">${model.description}</p>` : ""}
      </div>
      <div style="display:flex;gap:var(--space-2)">
        <button class="btn btn-primary btn-sm" onclick="openNewRunModalForModel(${model.id})">Run Pipeline</button>
        <button class="btn btn-secondary btn-sm" onclick="navigate('models')">Back</button>
      </div>
    </div>

    <div class="card animate-in" style="margin-bottom:var(--space-4)">
      <div class="card-header">
        <div class="card-title">Pipeline Runs</div>
      </div>
      ${
        model.runs.length > 0
          ? `
        <div class="table-wrapper">
          <table>
            <thead><tr><th>Run</th><th>Status</th><th>Started</th><th>Completed</th></tr></thead>
            <tbody>
              ${model.runs
                .map(
                  (r) => `
                <tr style="cursor:pointer" onclick="navigate('run-detail', ${r.id})">
                  <td class="mono">#${r.id}</td>
                  <td>${badgeHTML(r.status)}</td>
                  <td style="font-size:var(--text-xs)">${timeAgo(r.started_at)}</td>
                  <td style="font-size:var(--text-xs)">${r.completed_at ? timeAgo(r.completed_at) : "—"}</td>
                </tr>
              `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      `
          : '<div style="padding:var(--space-4);color:var(--color-text-faint);font-size:var(--text-sm)">No runs yet.</div>'
      }
    </div>

    ${
      model.incidents.length > 0
        ? `
      <div class="card animate-in">
        <div class="card-header">
          <div class="card-title">Incidents</div>
        </div>
        <div class="table-wrapper">
          <table>
            <thead><tr><th>Severity</th><th>Title</th><th>Status</th><th>Created</th></tr></thead>
            <tbody>
              ${model.incidents
                .map(
                  (i) => `
                <tr>
                  <td class="severity-${i.severity}">${i.severity}</td>
                  <td>${i.title}</td>
                  <td>${badgeHTML(i.status)}</td>
                  <td style="font-size:var(--text-xs)">${timeAgo(i.created_at)}</td>
                </tr>
              `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `
        : ""
    }
  `;
}

/* ===== Runs View ===== */

async function renderRuns(container) {
  container.innerHTML =
    '<div style="padding:var(--space-12);text-align:center;color:var(--color-text-faint)">Loading...</div>';

  try {
    runsData = await apiFetch("/api/runs");
  } catch {
    container.innerHTML =
      '<div class="empty-state"><h3>Cannot load runs</h3></div>';
    return;
  }

  if (runsData.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        <h3>No pipeline runs</h3>
        <p>Start a pipeline run to evaluate your model.</p>
        <button class="btn btn-primary" style="margin-top:var(--space-4)" onclick="openNewRunModal()">Start Run</button>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-5)">
      <div style="font-size:var(--text-sm);color:var(--color-text-muted)">${runsData.length} pipeline runs</div>
      <button class="btn btn-primary btn-sm" onclick="openNewRunModal()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5v14"/></svg>
        New Run
      </button>
    </div>
    <div class="card">
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Model</th>
              <th>Status</th>
              <th>Trigger</th>
              <th>Started</th>
              <th>Completed</th>
            </tr>
          </thead>
          <tbody>
            ${runsData
              .map(
                (r) => `
              <tr style="cursor:pointer" onclick="navigate('run-detail', ${r.id})">
                <td class="mono">#${r.id}</td>
                <td><strong>${r.model_name}</strong></td>
                <td>${badgeHTML(r.status)}</td>
                <td style="font-size:var(--text-xs);text-transform:capitalize">${r.trigger}</td>
                <td style="font-size:var(--text-xs)">${timeAgo(r.started_at)}</td>
                <td style="font-size:var(--text-xs)">${r.completed_at ? timeAgo(r.completed_at) : "—"}</td>
              </tr>
            `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

/* ===== Run Detail View ===== */

async function renderRunDetail(container, runId) {
  container.innerHTML =
    '<div style="padding:var(--space-12);text-align:center;color:var(--color-text-faint)">Loading...</div>';

  let run;
  try {
    run = await apiFetch(`/api/runs/${runId}`);
  } catch {
    container.innerHTML =
      '<div class="empty-state"><h3>Run not found</h3></div>';
    return;
  }

  currentRunDetail = run;
  document.getElementById("header-title").textContent = `Run #${run.id}`;

  const passedCount = run.stages.filter((s) => s.status === "passed").length;
  const warningCount = run.stages.filter((s) => s.status === "warning").length;
  const failedCount = run.stages.filter((s) => s.status === "failed").length;

  container.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--space-5)" class="animate-in">
      <div style="display:flex;align-items:center;gap:var(--space-3)">
        <strong style="font-size:var(--text-lg)">${run.model_name}</strong>
        ${badgeHTML(run.status)}
        <span class="mono" style="font-size:var(--text-xs);color:var(--color-text-faint)">Run #${run.id} · ${run.mode || "mock"} · ${run.trigger}</span>
      </div>
      <div style="display:flex;gap:var(--space-2)">
        <button class="btn btn-primary btn-sm" onclick="exportReleaseReport(${run.id})">
          Export Report
        </button>
        <button class="btn btn-secondary btn-sm" onclick="navigate('runs')">Back to Runs</button>
      </div>
    </div>

    <div class="kpi-grid animate-in" style="margin-bottom:var(--space-4)">
      <div class="kpi-card">
        <div class="kpi-label">Stages Passed</div>
        <div class="kpi-value" style="color:var(--color-success)">${passedCount}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Warnings</div>
        <div class="kpi-value" style="color:${warningCount > 0 ? "var(--color-warning)" : "var(--color-text-faint)"}">${warningCount}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Failed</div>
        <div class="kpi-value" style="color:${failedCount > 0 ? "var(--color-error)" : "var(--color-text-faint)"}">${failedCount}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Total Duration</div>
        <div class="kpi-value" style="font-size:var(--text-lg)">${run.completed_at ? formatDuration((new Date(run.completed_at) - new Date(run.started_at)) / 1000) : "Running..."}</div>
      </div>
    </div>

    <div class="card animate-in" style="margin-bottom:var(--space-5)">
      <div class="card-header">
        <div class="card-title">Pipeline</div>
      </div>
      <div class="pipeline-flow">
        ${run.stages
          .map(
            (s, i) => `
          <div class="pipeline-stage ${s.status}" onclick="scrollToStage('stage-${s.stage_key}')" title="${s.stage_name}: ${s.status}">
            <div class="stage-icon">${stageIcon(s.stage_key)}</div>
            <span class="stage-label">${s.stage_name.replace(" & ", " &amp; ")}</span>
            <span class="stage-duration">${formatDuration(s.duration_seconds)}</span>
          </div>
        `
          )
          .join("")}
      </div>
    </div>

    ${run.stages.map((s) => renderStageDetail(s)).join("")}
  `;
}

async function exportReleaseReport(runId) {
  try {
    const markdown = await apiFetchText(
      `/api/runs/${runId}/release-report?format=markdown`
    );
    downloadTextFile(`kiln-run-${runId}-release-report.md`, markdown);
  } catch (err) {
    alert("Failed to export report: " + err.message);
  }
}

function scrollToStage(id) {
  const el = document.getElementById(id);
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function renderStageDetail(stage) {
  const results = stage.results || {};

  return `
    <div class="stage-detail animate-in" id="stage-${stage.stage_key}">
      <div class="stage-detail-header">
        <div class="stage-detail-title">
          ${stageIcon(stage.stage_key)}
          <h3>${stage.stage_name}</h3>
          ${badgeHTML(stage.status)}
        </div>
        <span class="mono" style="font-size:var(--text-xs);color:var(--color-text-faint)">${formatDuration(stage.duration_seconds)}</span>
      </div>
      <div class="stage-detail-body">
        ${renderStageResults(stage.stage_key, results)}
      </div>
    </div>
  `;
}

function renderStageResults(key, results) {
  switch (key) {
    case "benchmarks":
      return renderBenchmarkResults(results);
    case "safety":
      return renderSafetyResults(results);
    case "documentation":
      return renderDocResults(results);
    case "packaging":
      return renderPackagingResults(results);
    case "serving":
      return renderServingResults(results);
    case "monitoring":
      return renderMonitoringResults(results);
    case "incidents":
      return renderIncidentResults(results);
    case "improvement":
      return renderImprovementResults(results);
    default:
      return `<pre class="mono" style="font-size:var(--text-xs);white-space:pre-wrap;color:var(--color-text-muted)">${JSON.stringify(results, null, 2)}</pre>`;
  }
}

function renderBenchmarkResults(results) {
  if (!results.benchmarks) {
    return '<div style="color:var(--color-text-faint)">No benchmark data</div>';
  }

  return `
    ${results.tool ? `<div class="stage-detail-meta"><div class="meta-item"><span class="meta-label">Tool</span><span class="meta-value mono" style="font-size:var(--text-xs)">${results.tool}</span></div></div>` : ""}
    <div class="table-wrapper">
      <table>
        <thead><tr><th>Benchmark</th><th style="width:40%">Score</th><th>Result</th></tr></thead>
        <tbody>
          ${results.benchmarks
            .map((b) => {
              const pct = Math.min(b.score, 100);
              const targetPct = b.target_min || 0;
              return `
              <tr>
                <td><strong>${b.name}</strong></td>
                <td>
                  <div class="benchmark-bar-container">
                    <div class="benchmark-bar">
                      <div class="benchmark-bar-fill ${b.status}" style="width:${pct}%"></div>
                      ${targetPct > 0 ? `<div class="benchmark-bar-target" style="left:${targetPct}%"></div>` : ""}
                    </div>
                    <span class="benchmark-score" style="color:${b.status === "pass" ? "var(--color-success)" : "var(--color-error)"}">${b.score}%</span>
                  </div>
                </td>
                <td>${badgeHTML(b.status === "pass" ? "passed" : "failed")}</td>
              </tr>
            `;
            })
            .join("")}
        </tbody>
      </table>
    </div>
    ${results.ablation_summary ? `<div style="margin-top:var(--space-4);padding:var(--space-3) var(--space-4);background:var(--color-primary-subtle);border-radius:var(--radius-md);font-size:var(--text-sm);color:var(--color-text-muted)"><strong style="color:var(--color-primary)">Ablation:</strong> ${results.ablation_summary}</div>` : ""}
  `;
}

function renderSafetyResults(results) {
  let html = '<div class="metric-grid" style="margin-bottom:var(--space-4)">';

  if (results.toxicity) {
    const t = results.toxicity;
    html += `
      <div class="metric-item">
        <span class="meta-label">Max Toxicity</span>
        <span class="meta-value" style="color:${t.expected_max_toxicity < 0.5 ? "var(--color-success)" : "var(--color-error)"}">${t.expected_max_toxicity}</span>
        ${t.gpt2_xl_baseline ? `<span class="meta-label">GPT-2 XL: ${t.gpt2_xl_baseline}</span>` : ""}
      </div>
      <div class="metric-item">
        <span class="meta-label">Toxicity Probability</span>
        <span class="meta-value">${(t.toxicity_probability * 100).toFixed(1)}%</span>
      </div>
    `;
  }

  if (results.truthfulness) {
    html += `
      <div class="metric-item">
        <span class="meta-label">TruthfulQA</span>
        <span class="meta-value" style="color:var(--color-success)">${results.truthfulness.truthfulqa_score}%</span>
      </div>
    `;
  }

  if (results.red_team) {
    html += `
      <div class="metric-item">
        <span class="meta-label">Red Team</span>
        <span class="meta-value" style="font-size:var(--text-sm)">${badgeHTML(results.red_team.status)}</span>
        ${results.red_team.note ? `<span class="meta-label" style="margin-top:var(--space-1)">${results.red_team.note}</span>` : ""}
      </div>
    `;
  }

  html += "</div>";

  if (results.bias && results.bias.categories) {
    html += `
      <div style="margin-top:var(--space-4)">
        <div style="font-size:var(--text-sm);font-weight:600;margin-bottom:var(--space-3)">Bias by Category <span style="font-weight:400;color:var(--color-text-faint)">(ideal: 50%, lower = less biased)</span></div>
        <div class="bias-grid">
          ${Object.entries(results.bias.categories)
            .map(([cat, score]) => {
              const cls =
                score <= 52 ? "good" : score <= 58 ? "caution" : "concern";
              return `
              <div class="bias-cell">
                <div class="bias-category">${cat}</div>
                <div class="bias-score ${cls}">${score}%</div>
              </div>
            `;
            })
            .join("")}
        </div>
      </div>
    `;
    if (results.bias.note) {
      html += `<div style="margin-top:var(--space-3);padding:var(--space-3) var(--space-4);background:var(--color-warning-subtle);border-radius:var(--radius-md);font-size:var(--text-sm);color:var(--color-text-muted)"><strong style="color:var(--color-warning)">Note:</strong> ${results.bias.note}</div>`;
    }
  }

  return html;
}

function renderDocResults(results) {
  if (results.checklist) {
    return `
      <div style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:var(--space-4)">
        <span style="font-size:var(--text-sm);font-weight:600">${results.checklist.filter((c) => c.complete).length}/${results.checklist.length} complete</span>
        <div style="flex:1;height:6px;background:var(--color-surface-3);border-radius:var(--radius-full);overflow:hidden">
          <div style="width:${(results.checklist.filter((c) => c.complete).length / results.checklist.length) * 100}%;height:100%;background:var(--color-success);border-radius:var(--radius-full)"></div>
        </div>
      </div>
      <ul class="checklist">
        ${results.checklist
          .map(
            (c) => `
          <li class="checklist-item">
            <span class="checklist-icon ${c.complete ? "complete" : "incomplete"}">
              ${c.complete ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>' : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>'}
            </span>
            <div>
              <span>${c.item}</span>
              ${c.note ? `<div class="checklist-note">${c.note}</div>` : ""}
            </div>
          </li>
        `
          )
          .join("")}
      </ul>
    `;
  }

  return `
    <div class="metric-grid">
      <div class="metric-item">
        <span class="meta-label">Completeness</span>
        <span class="meta-value">${Math.round((results.completeness || 0) * 100)}%</span>
      </div>
      <div class="metric-item">
        <span class="meta-label">Checklist</span>
        <span class="meta-value">${results.checklist_complete || 0}/${results.checklist_total || 8}</span>
      </div>
    </div>
  `;
}

function renderPackagingResults(results) {
  let html = "";

  if (results.huggingface) {
    const hf = results.huggingface;
    html += `<div style="margin-bottom:var(--space-4)"><span class="badge badge-passed">HuggingFace Uploaded</span>`;
    if (hf.repo_url) {
      html += ` <a href="${hf.repo_url}" target="_blank" rel="noopener noreferrer" class="mono" style="font-size:var(--text-xs);color:var(--color-primary);margin-left:var(--space-2)">${hf.repo_url}</a>`;
    }
    html += `</div>`;

    if (hf.files) {
      html += `
        <div style="margin-bottom:var(--space-4)">
          <div style="font-size:var(--text-sm);font-weight:600;margin-bottom:var(--space-2)">Repository Files</div>
          <div class="table-wrapper">
            <table>
              <thead><tr><th>File</th><th>Size</th></tr></thead>
              <tbody>
                ${hf.files
                  .map(
                    (f) => `
                  <tr>
                    <td class="mono" style="font-size:var(--text-xs)">${typeof f === "string" ? f : f.name}</td>
                    <td class="mono" style="font-size:var(--text-xs);color:var(--color-text-faint)">${typeof f === "string" ? "" : f.size || ""}</td>
                  </tr>
                `
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        </div>
      `;
    }
  }

  if (results.quantized_variants) {
    html += `
      <div style="font-size:var(--text-sm);font-weight:600;margin-bottom:var(--space-2)">Quantized Variants</div>
      ${results.quantized_variants
        .map(
          (q) => `
        <div class="quant-card">
          <span class="quant-format">${q.format}</span>
          <div class="quant-meta">
            <span>${q.size_gb} GB</span>
            ${q.vram_required ? `<span>VRAM: ${q.vram_required}</span>` : ""}
            ${badgeHTML(q.status === "ready" ? "passed" : "pending")}
          </div>
        </div>
      `
        )
        .join("")}
    `;
  }

  return html || '<div style="color:var(--color-text-faint)">No data</div>';
}

function renderServingResults(results) {
  let html = `
    <div class="stage-detail-meta">
      ${results.engine ? `<div class="meta-item"><span class="meta-label">Engine</span><span class="meta-value mono">${results.engine}</span></div>` : ""}
      ${results.endpoint ? `<div class="meta-item"><span class="meta-label">Endpoint</span><span class="meta-value mono" style="font-size:var(--text-xs)">${results.endpoint}</span></div>` : ""}
      ${results.health ? `<div class="meta-item"><span class="meta-label">Health</span><span class="meta-value">${badgeHTML(results.health)}</span></div>` : ""}
    </div>
  `;

  if (results.metrics) {
    const m = results.metrics;
    html += `
      <div class="metric-grid">
        ${m.ttft_p50_ms !== undefined ? `<div class="metric-item"><span class="meta-label">TTFT p50</span><span class="meta-value">${m.ttft_p50_ms}ms</span></div>` : ""}
        ${m.ttft_p99_ms !== undefined ? `<div class="metric-item"><span class="meta-label">TTFT p99</span><span class="meta-value">${m.ttft_p99_ms}ms</span></div>` : ""}
        ${m.tpot_ms !== undefined ? `<div class="metric-item"><span class="meta-label">TPOT</span><span class="meta-value">${m.tpot_ms}ms/tok</span></div>` : ""}
        ${m.throughput_rps !== undefined ? `<div class="metric-item"><span class="meta-label">Throughput</span><span class="meta-value">${m.throughput_rps} RPS</span></div>` : ""}
        ${m.gpu_utilization !== undefined ? `<div class="metric-item"><span class="meta-label">GPU Util</span><span class="meta-value">${Math.round(m.gpu_utilization * 100)}%</span></div>` : ""}
        ${m.memory_used_gb !== undefined ? `<div class="metric-item"><span class="meta-label">Memory</span><span class="meta-value">${m.memory_used_gb} GB</span></div>` : ""}
        ${m.kv_cache_utilization !== undefined ? `<div class="metric-item"><span class="meta-label">KV Cache</span><span class="meta-value">${Math.round(m.kv_cache_utilization * 100)}%</span></div>` : ""}
      </div>
    `;
  }

  if (results.load_test) {
    const lt = results.load_test;
    html += `
      <div style="margin-top:var(--space-4);padding:var(--space-3) var(--space-4);background:var(--color-surface-2);border-radius:var(--radius-md)">
        <div style="font-size:var(--text-xs);font-weight:600;margin-bottom:var(--space-2)">Load Test</div>
        <div style="font-size:var(--text-xs);color:var(--color-text-muted)">
          ${lt.concurrent_users} concurrent users &middot; ${lt.duration_seconds}s &middot;
          ${lt.requests_completed.toLocaleString()} completed &middot; ${lt.errors} errors &middot;
          p99: ${lt.p99_latency_ms}ms
        </div>
      </div>
    `;
  }

  if (results.model_config) {
    html += `
      <div style="margin-top:var(--space-4)">
        <div style="font-size:var(--text-xs);font-weight:600;margin-bottom:var(--space-2)">Model Config</div>
        <pre class="mono" style="font-size:var(--text-xs);color:var(--color-text-faint);background:var(--color-surface-2);padding:var(--space-3);border-radius:var(--radius-md);white-space:pre-wrap">${JSON.stringify(results.model_config, null, 2)}</pre>
      </div>
    `;
  }

  return html;
}

function renderMonitoringResults(results) {
  return `
    <div class="metric-grid">
      <div class="metric-item">
        <span class="meta-label">Status</span>
        <span class="meta-value">${badgeHTML(results.status === "active" ? "passed" : "pending")}</span>
      </div>
      ${results.uptime_hours !== undefined ? `<div class="metric-item"><span class="meta-label">Uptime</span><span class="meta-value">${results.uptime_hours}h</span></div>` : ""}
      ${results.total_requests !== undefined ? `<div class="metric-item"><span class="meta-label">Total Requests</span><span class="meta-value">${results.total_requests.toLocaleString()}</span></div>` : ""}
      ${results.error_rate !== undefined ? `<div class="metric-item"><span class="meta-label">Error Rate</span><span class="meta-value" style="color:${results.error_rate < 0.01 ? "var(--color-success)" : "var(--color-error)"}">${(results.error_rate * 100).toFixed(2)}%</span></div>` : ""}
      ${results.avg_latency_ms !== undefined ? `<div class="metric-item"><span class="meta-label">Avg Latency</span><span class="meta-value">${results.avg_latency_ms}ms</span></div>` : ""}
      <div class="metric-item">
        <span class="meta-label">Drift Detected</span>
        <span class="meta-value" style="color:${results.drift_detected ? "var(--color-error)" : "var(--color-success)"}">${results.drift_detected ? "Yes" : "No"}</span>
      </div>
    </div>
    ${
      results.toxicity_monitoring
        ? `
      <div style="margin-top:var(--space-4);padding:var(--space-3) var(--space-4);background:var(--color-surface-2);border-radius:var(--radius-md)">
        <div style="font-size:var(--text-xs);font-weight:600;margin-bottom:var(--space-1)">Toxicity Monitoring</div>
        <div style="font-size:var(--text-xs);color:var(--color-text-muted)">
          ${results.toxicity_monitoring.samples_checked} samples checked &middot;
          ${results.toxicity_monitoring.alerts} alerts &middot;
          Last: ${timeAgo(results.toxicity_monitoring.last_checked)}
        </div>
      </div>
    `
        : ""
    }
    ${
      results.drift_detection
        ? `
      <div style="margin-top:var(--space-2);padding:var(--space-3) var(--space-4);background:var(--color-surface-2);border-radius:var(--radius-md)">
        <div style="font-size:var(--text-xs);font-weight:600;margin-bottom:var(--space-1)">Drift Detection</div>
        <div style="font-size:var(--text-xs);color:var(--color-text-muted)">
          Input: ${results.drift_detection.input_drift ? "Detected" : "None"} &middot;
          Output: ${results.drift_detection.output_drift ? "Detected" : "None"} &middot;
          Performance: ${results.drift_detection.performance_drift ? "Detected" : "None"} &middot;
          Last: ${timeAgo(results.drift_detection.last_checked)}
        </div>
      </div>
    `
        : ""
    }
    ${
      results.tools
        ? `
      <div style="margin-top:var(--space-4);font-size:var(--text-xs);color:var(--color-text-faint)">
        <strong>Tools:</strong> ${results.tools.join(", ")}
      </div>
    `
        : ""
    }
  `;
}

function renderIncidentResults(results) {
  let html = `
    <div class="metric-grid" style="margin-bottom:var(--space-4)">
      <div class="metric-item">
        <span class="meta-label">Total</span>
        <span class="meta-value">${results.total_incidents || 0}</span>
      </div>
      <div class="metric-item">
        <span class="meta-label">Open</span>
        <span class="meta-value" style="color:${(results.open_incidents || 0) > 0 ? "var(--color-error)" : "var(--color-success)"}">${results.open_incidents || 0}</span>
      </div>
      <div class="metric-item">
        <span class="meta-label">Runbook</span>
        <span class="meta-value">${results.runbook_exists ? "Ready" : "Missing"}</span>
      </div>
      <div class="metric-item">
        <span class="meta-label">Kill Switch</span>
        <span class="meta-value">${results.kill_switch_tested ? "Tested" : "Untested"}</span>
      </div>
    </div>
  `;

  if (results.incidents && results.incidents.length > 0) {
    html += `
      <div class="table-wrapper">
        <table>
          <thead><tr><th>Severity</th><th>Title</th><th>Status</th><th>Resolution</th></tr></thead>
          <tbody>
            ${results.incidents
              .map(
                (i) => `
              <tr>
                <td class="severity-${i.severity}">${i.severity}</td>
                <td>${i.title}</td>
                <td>${badgeHTML(i.status)}</td>
                <td style="font-size:var(--text-xs);color:var(--color-text-muted);max-width:300px">${i.resolution || "—"}</td>
              </tr>
            `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  return html;
}

function renderImprovementResults(results) {
  let html = "";

  if (results.current_cycle) {
    html += `<div style="margin-bottom:var(--space-4)"><span class="badge badge-running">${results.current_cycle}</span></div>`;
  }

  if (results.next_actions) {
    html += `
      <div style="font-size:var(--text-sm);font-weight:600;margin-bottom:var(--space-2)">Next Actions</div>
      <ul class="checklist" style="margin-bottom:var(--space-4)">
        ${(Array.isArray(results.next_actions) ? results.next_actions : [])
          .map((a) => {
            const text = typeof a === "string" ? a : a.action;
            const priority = typeof a === "object" ? a.priority : null;
            const due = typeof a === "object" ? a.due : null;
            return `
            <li class="checklist-item">
              <span class="checklist-icon incomplete"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg></span>
              <div>
                <span>${text}</span>
                ${priority || due ? `<div class="checklist-note">${priority ? `Priority: ${priority}` : ""}${priority && due ? " · " : ""}${due ? `Due: ${due}` : ""}</div>` : ""}
              </div>
            </li>
          `;
          })
          .join("")}
      </ul>
    `;
  }

  if (results.review_schedule) {
    html += `
      <div style="font-size:var(--text-sm);font-weight:600;margin-bottom:var(--space-2)">Review Schedule</div>
      <div class="metric-grid">
        ${Object.entries(results.review_schedule)
          .map(
            ([period, desc]) => `
          <div class="metric-item">
            <span class="meta-label" style="text-transform:capitalize">${period}</span>
            <span class="meta-value" style="font-size:var(--text-xs);font-weight:400">${desc}</span>
          </div>
        `
          )
          .join("")}
      </div>
    `;
  }

  return (
    html || '<div style="color:var(--color-text-faint)">No improvement data</div>'
  );
}

/* ===== Incidents View ===== */

async function renderIncidents(container) {
  container.innerHTML =
    '<div style="padding:var(--space-12);text-align:center;color:var(--color-text-faint)">Loading...</div>';

  try {
    incidentsData = await apiFetch("/api/incidents");
  } catch {
    container.innerHTML =
      '<div class="empty-state"><h3>Cannot load incidents</h3></div>';
    return;
  }

  if (incidentsData.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        <h3>No incidents</h3>
        <p>No incidents have been reported. That is a good thing.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div style="margin-bottom:var(--space-5)">
      <div style="font-size:var(--text-sm);color:var(--color-text-muted)">${incidentsData.length} incidents</div>
    </div>
    <div class="card">
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Severity</th>
              <th>Title</th>
              <th>Model</th>
              <th>Status</th>
              <th>Created</th>
              <th>Resolved</th>
            </tr>
          </thead>
          <tbody>
            ${incidentsData
              .map(
                (i) => `
              <tr>
                <td class="severity-${i.severity}" style="font-weight:700">${i.severity}</td>
                <td>
                  <div><strong>${i.title}</strong></div>
                  ${i.description ? `<div style="font-size:var(--text-xs);color:var(--color-text-faint);margin-top:2px">${i.description}</div>` : ""}
                </td>
                <td>${i.model_name}</td>
                <td>${badgeHTML(i.status)}</td>
                <td style="font-size:var(--text-xs)">${timeAgo(i.created_at)}</td>
                <td style="font-size:var(--text-xs)">${i.resolved_at ? timeAgo(i.resolved_at) : "—"}</td>
              </tr>
            `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Update badge
  const openCount = incidentsData.filter((i) => i.status === "open").length;
  const badge = document.getElementById("incident-badge");
  if (badge) {
    if (openCount > 0) {
      badge.textContent = openCount;
      badge.style.display = "";
    } else {
      badge.style.display = "none";
    }
  }
}

/* ===== About View ===== */

function renderAbout(container) {
  container.innerHTML = `
    <div style="max-width:720px" class="animate-in">
      <div style="display:flex;align-items:center;gap:var(--space-4);margin-bottom:var(--space-8)">
        <svg width="48" height="48" viewBox="0 0 32 32" fill="none">
          <rect x="4" y="10" width="24" height="18" rx="3" fill="var(--color-primary)"/>
          <rect x="8" y="4" width="16" height="10" rx="2" fill="var(--color-warning)"/>
          <rect x="10" y="14" width="4" height="4" rx="1" fill="white" opacity="0.9"/>
          <rect x="18" y="14" width="4" height="4" rx="1" fill="white" opacity="0.9"/>
          <rect x="10" y="22" width="12" height="2" rx="1" fill="white" opacity="0.5"/>
        </svg>
        <div>
          <h2 style="font-size:var(--text-2xl);font-weight:700;letter-spacing:-0.02em">Kiln</h2>
          <p style="color:var(--color-text-muted);font-size:var(--text-sm)">Open-source LLMOps Pipeline Manager</p>
        </div>
      </div>

      <div class="card" style="margin-bottom:var(--space-4)">
        <div class="card-title" style="margin-bottom:var(--space-3)">What is Kiln?</div>
        <p style="font-size:var(--text-sm);color:var(--color-text-muted);line-height:1.7">
          Kiln is a model-to-production pipeline manager for LLMs. It orchestrates the 8 stages
          that happen between "my model trained" and "my model is in production": academic benchmarks,
          safety evaluation, documentation, packaging, inference serving, monitoring, incident response,
          and continuous improvement.
        </p>
        <p style="font-size:var(--text-sm);color:var(--color-text-muted);line-height:1.7;margin-top:var(--space-3)">
          v0.1 ships with mock mode plus one real adapter path for benchmarks via lm-eval-harness.
          Other stages are manual or mock unless you add adapters.
        </p>
      </div>

      <div class="card" style="margin-bottom:var(--space-4)">
        <div class="card-title" style="margin-bottom:var(--space-3)">Pipeline Stages</div>
        <div class="table-wrapper">
          <table>
            <thead><tr><th>Stage</th><th>What It Does</th><th>Tools</th></tr></thead>
            <tbody>
              <tr><td><strong>1. Benchmarks</strong></td><td>MMLU, HellaSwag, ARC, WinoGrande, TruthfulQA, GSM8K</td><td class="mono" style="font-size:var(--text-xs)">lm-eval-harness</td></tr>
              <tr><td><strong>2. Safety</strong></td><td>Toxicity, bias (CrowS-Pairs), truthfulness, red teaming</td><td class="mono" style="font-size:var(--text-xs)">Manual/mock in v0.1</td></tr>
              <tr><td><strong>3. Documentation</strong></td><td>Model card, intended use, limitations, NIST alignment</td><td class="mono" style="font-size:var(--text-xs)">Manual/mock in v0.1</td></tr>
              <tr><td><strong>4. Packaging</strong></td><td>HuggingFace upload, GGUF/AWQ quantization</td><td class="mono" style="font-size:var(--text-xs)">Manual/mock in v0.1</td></tr>
              <tr><td><strong>5. Serving</strong></td><td>Inference API, latency/throughput metrics</td><td class="mono" style="font-size:var(--text-xs)">Manual/mock in v0.1</td></tr>
              <tr><td><strong>6. Monitoring</strong></td><td>Drift detection, toxicity sampling, performance tracking</td><td class="mono" style="font-size:var(--text-xs)">Manual/mock in v0.1</td></tr>
              <tr><td><strong>7. Incidents</strong></td><td>Incident tracking, runbook, kill switch</td><td class="mono" style="font-size:var(--text-xs)">Manual/mock in v0.1</td></tr>
              <tr><td><strong>8. Improvement</strong></td><td>Feedback loops, scheduled reviews, retrain triggers</td><td class="mono" style="font-size:var(--text-xs)">Manual/mock in v0.1</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card" style="margin-bottom:var(--space-4)">
        <div class="card-title" style="margin-bottom:var(--space-3)">Quick Start</div>
        <pre class="mono" style="font-size:var(--text-xs);background:var(--color-surface-2);padding:var(--space-4);border-radius:var(--radius-md);overflow-x:auto;line-height:1.8;color:var(--color-text-muted)"><span style="color:var(--color-text-faint)"># Clone the repo</span>
git clone https://github.com/anthony-maio/kiln.git
cd kiln

<span style="color:var(--color-text-faint)"># Run with Docker</span>
docker compose up --build

<span style="color:var(--color-text-faint)"># Or run locally</span>
pip install -r requirements.txt
python api_server.py</pre>
      </div>

      <div class="card">
        <div class="card-title" style="margin-bottom:var(--space-3)">Credits</div>
        <p style="font-size:var(--text-sm);color:var(--color-text-muted)">
          Built by <strong>Anthony Maio</strong> &mdash; Making Minds AI<br>
          <a href="https://making-minds.ai" target="_blank" rel="noopener noreferrer" style="color:var(--color-primary)">making-minds.ai</a>
        </p>
        <p style="font-size:var(--text-xs);color:var(--color-text-faint);margin-top:var(--space-2)">
          Version 0.1.0 &middot; MIT License &middot; March 2026
        </p>
      </div>
    </div>
  `;
}

/* ===== Modals ===== */

function openModal(id) {
  document.getElementById(id).classList.add("active");
}

function closeModal(id) {
  document.getElementById(id).classList.remove("active");
}

async function openNewRunModal() {
  try {
    const models = await apiFetch("/api/models");
    const select = document.getElementById("run-model-select");
    select.innerHTML = models
      .map(
        (m) =>
          `<option value="${m.id}">${m.name} (${m.parameters || "unknown"})</option>`
      )
      .join("");
  } catch {
    /* empty */
  }
  openModal("new-run-modal");
}

function openNewRunModalForModel(modelId) {
  openNewRunModal().then(() => {
    document.getElementById("run-model-select").value = modelId;
  });
}

function openNewModelModal() {
  openModal("new-model-modal");
}

async function startNewRun() {
  const modelId = parseInt(
    document.getElementById("run-model-select").value,
    10
  );
  const mode = document.getElementById("run-mode-select").value;

  try {
    const run = await apiPost("/api/runs", {
      model_id: modelId,
      mode: mode,
    });
    closeModal("new-run-modal");
    navigate("run-detail", run.id);
  } catch (err) {
    alert("Failed to start run: " + err.message);
  }
}

async function registerModel() {
  const name = document.getElementById("model-name-input").value.trim();
  if (!name) {
    alert("Model name is required");
    return;
  }

  try {
    await apiPost("/api/models", {
      name: name,
      repo_id:
        document.getElementById("model-repo-input").value.trim() || null,
      parameters:
        document.getElementById("model-params-input").value.trim() || null,
      architecture:
        document.getElementById("model-arch-input").value.trim() || null,
      description:
        document.getElementById("model-desc-input").value.trim() || null,
    });
    closeModal("new-model-modal");

    document.getElementById("model-name-input").value = "";
    document.getElementById("model-repo-input").value = "";
    document.getElementById("model-params-input").value = "";
    document.getElementById("model-arch-input").value = "";
    document.getElementById("model-desc-input").value = "";

    navigate("models");
  } catch (err) {
    alert("Failed to register model: " + err.message);
  }
}

/* Close modals on overlay click */
document.querySelectorAll(".modal-overlay").forEach((overlay) => {
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) {
      overlay.classList.remove("active");
    }
  });
});

/* ===== Init ===== */
navigate("dashboard");
