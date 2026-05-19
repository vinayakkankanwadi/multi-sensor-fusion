"use strict";

const $ = (sel) => document.querySelector(sel);

// v7 = Nodes + Middleware drawers consolidated. There is now one
//      selected send target (a middleware-type node); we persist its
//      id under `target_node_id`. The pre-merge `middleware_id` /
//      `node_id_selection` keys are no longer read.
const STORE_KEY = "msf_endpoint_v7";

function loadEndpoint() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
  catch { return {}; }
}
function saveEndpoint() {
  const data = {
    target_node_id: selectedTargetId,
    node_id: $("#node-id").value.trim(),
    recv_timeout_s: Number($("#recv-timeout").value),
    drain_after_s: Number($("#drain-after").value),
    validate_before_send: $("#validate-before").checked,
    auto_new_uuid: $("#auto-new-uuid").checked,
  };
  localStorage.setItem(STORE_KEY, JSON.stringify(data));
}

// Nodes registry — drives the unified drawer (platform-node + middleware
// today; edge-node / tak-server / fusion-node tomorrow). The selected
// send target is always a middleware-type entry; other types render
// without a radio.
let nodeList = [];
let selectedTargetId = null;

function selectedTarget() {
  return nodeList.find((n) => n.id === selectedTargetId &&
                              n.type === "middleware") || null;
}

function ensureUUID() {
  // If auto-new-uuid is on, mint a fresh UUID for this run and update the field.
  if ($("#auto-new-uuid").checked) {
    $("#node-id").value = newUUID();
    saveEndpoint();
  } else if (!$("#node-id").value.trim()) {
    $("#node-id").value = newUUID();
    saveEndpoint();
  }
  return $("#node-id").value.trim();
}

function newUUID() {
  if (crypto?.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = Math.random() * 16 | 0;
    return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

let currentTemplate = null;

async function loadTemplates() {
  const list = $("#template-list");
  list.innerHTML = "";
  const r = await fetch("/api/templates");
  if (!r.ok) {
    list.innerHTML = `<li class="muted">load failed: ${r.status}</li>`;
    return;
  }
  const templates = await r.json();
  for (const t of templates) {
    const li = document.createElement("li");
    li.textContent = t.name;
    li.dataset.name = t.name;
    li.addEventListener("click", () => selectTemplate(t.name));
    list.appendChild(li);
  }
  if (templates.length === 0) {
    list.innerHTML = `<li class="muted">No templates. Click <em>Build from .proto</em> or drop a .json into <code>templates/</code>.</li>`;
    return;
  }
  if (!currentTemplate) {
    setEditorTemplate(templates[0].name);
  } else if (templates.find((t) => t.name === currentTemplate)) {
    setEditorTemplate(currentTemplate);
  }
}

let mode = "single";  // "single" or "flow"
let flowSteps = [];   // [{template_name, wait_for, recv_timeout_s, drain_after_s}]
const editBuffer = {};  // template_name -> in-progress editor text

function highlightTemplate(name) {
  document.querySelectorAll("#template-list li").forEach((li) => {
    li.classList.toggle("active", li.dataset.name === name);
  });
}

async function selectTemplate(name) {
  highlightTemplate(name);
  // Always load into the editor so the body is visible and editable in
  // both modes. In flow mode, also append it as a step — the per-template
  // editBuffer captures any in-progress edits and they're sent at run time.
  await setEditorTemplate(name);
  if (mode === "flow") {
    addFlowStep(name);
  }
}

async function setEditorTemplate(name) {
  // Preserve in-progress edits in the previous template before swapping.
  // Cleared explicitly by "Reload from disk", or implicitly on Clear /
  // Build from .proto (the canonical source has changed).
  if (currentTemplate && currentTemplate !== name) {
    editBuffer[currentTemplate] = $("#editor").value;
  }
  currentTemplate = name;
  highlightTemplate(name);
  $("#editor-title").textContent = name;
  if (name in editBuffer) {
    $("#editor").value = editBuffer[name];
  } else {
    await reloadFromDisk();
  }
  $("#validate-only").disabled = false;
  $("#reload-template").disabled = false;
  refreshSendButton();
}

function setMode(newMode) {
  mode = newMode;
  $("#mode-single").classList.toggle("active", mode === "single");
  $("#mode-flow").classList.toggle("active", mode === "flow");
  // Editor (#single-pane) stays visible in both modes so users can preview
  // and edit message bodies. Send is single-only; Run flow / Clear belong
  // to flow-pane.
  $("#single-pane").hidden = false;
  $("#flow-pane").hidden = mode !== "flow";
  $("#send").hidden = mode === "flow";
  document.querySelectorAll("#template-list li").forEach((li) => {
    li.title = mode === "flow"
      ? "click to load into the editor AND append as the next flow step"
      : "click to load into the editor";
  });
  refreshSendButton();
}

const ACK_FOR = {
  registration: "registration_ack",
  alert: "alert_ack",
};

function addFlowStep(template_name) {
  flowSteps.push({
    template_name,
    wait_for: ACK_FOR[template_name] || "",
    recv_timeout_s: ACK_FOR[template_name] ? 5.0 : 1.0,
    drain_after_s: 0.5,
  });
  renderFlow();
}

function removeFlowStep(idx) {
  flowSteps.splice(idx, 1);
  renderFlow();
}

function moveFlowStep(idx, dir) {
  const j = idx + dir;
  if (j < 0 || j >= flowSteps.length) return;
  [flowSteps[idx], flowSteps[j]] = [flowSteps[j], flowSteps[idx]];
  renderFlow();
}

function renderFlow() {
  const tbody = $("#flow-table tbody");
  tbody.innerHTML = "";
  $("#flow-empty").hidden = flowSteps.length > 0;
  for (const [i, step] of flowSteps.entries()) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td>${step.template_name}</td>
      <td><input type="text" placeholder="(none)" value="${step.wait_for || ""}" data-i="${i}" data-k="wait_for"></td>
      <td><input type="number" step="0.5" min="0" max="60" value="${step.recv_timeout_s}" data-i="${i}" data-k="recv_timeout_s"></td>
      <td><input type="number" step="0.1" min="0" max="60" value="${step.drain_after_s}" data-i="${i}" data-k="drain_after_s"></td>
      <td class="actions">
        <button data-i="${i}" data-act="up">↑</button>
        <button data-i="${i}" data-act="down">↓</button>
        <button data-i="${i}" data-act="rm">✕</button>
      </td>`;
    tbody.appendChild(tr);
  }
  $("#run-flow").disabled = flowSteps.length === 0;
  // bind events
  tbody.querySelectorAll("input").forEach((el) => {
    el.addEventListener("change", (e) => {
      const i = +e.target.dataset.i, k = e.target.dataset.k;
      flowSteps[i][k] = e.target.type === "number" ? Number(e.target.value) : e.target.value;
    });
  });
  tbody.querySelectorAll("button[data-act]").forEach((b) => {
    b.addEventListener("click", (e) => {
      const i = +e.target.dataset.i;
      const a = e.target.dataset.act;
      if (a === "up")   moveFlowStep(i, -1);
      if (a === "down") moveFlowStep(i, +1);
      if (a === "rm")   removeFlowStep(i);
    });
  });
}

async function runFlow() {
  if (!flowSteps.length) return;
  const mw = selectedTarget();
  if (!mw) {
    $("#flow-status").textContent = "select a middleware in the Nodes drawer first";
    return;
  }
  saveEndpoint();
  $("#flow-status").textContent = "running flow...";
  $("#run-flow").disabled = true;
  try {
    // Snapshot the editor's current text into the buffer so the currently
    // visible template's edits are included alongside any earlier ones.
    if (currentTemplate) {
      editBuffer[currentTemplate] = $("#editor").value;
    }
    const body = {
      host: mw.host,
      port: mw.port,
      node_id: ensureUUID(),
      validate_before_send: $("#validate-before").checked,
      steps: flowSteps.map((s) => {
        const step = {
          template_name: s.template_name,
          wait_for: s.wait_for || null,
          recv_timeout_s: s.recv_timeout_s,
          drain_after_s: s.drain_after_s,
        };
        if (s.template_name in editBuffer) {
          step.raw_json = editBuffer[s.template_name];
        }
        return step;
      }),
    };
    const r = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      showError(err.detail || `HTTP ${r.status}`);
      return;
    }
    const result = await r.json();
    showFlowResult(result);
    await loadRecentRuns();
  } catch (exc) {
    showError(String(exc));
  } finally {
    $("#run-flow").disabled = false;
    $("#flow-status").textContent = "";
  }
}

function showFlowResult(result) {
  const sum = $("#result-summary");
  const ve = $("#validation-errors");
  ve.innerHTML = "";
  const nrecv = (result.transcript || []).filter((t) => t.direction === "recv").length;
  if (result.error) {
    sum.className = "err";
    sum.textContent = `${result.run_id} → flow failed: ${result.error}`;
  } else {
    sum.className = "ok";
    sum.textContent = `${result.run_id} → flow ok, ${result.steps.length} step(s), ${nrecv} reply(ies)`;
  }
  // Per-step summary — render defensively even when fields are missing.
  const stepLines = (result.steps || []).map((s, i) => {
    const idx = (typeof s.index === "number" ? s.index : i) + 1;
    const tpl = s.template || "?";
    const recv = (typeof s.recv_count === "number") ? s.recv_count : 0;
    const matched = s.matched_wait_for || (s.wait_for ? "(timeout)" : "—");
    const skipped = s.skipped ? "  (skipped)" : "";
    const errFlag = s.error ? `  ERR: ${s.error}` : "";
    return `step ${idx}  ${tpl.padEnd(18)} recv=${recv}  matched=${matched}${skipped}${errFlag}`;
  });
  $("#result-transcript").textContent =
    stepLines.join("\n") + "\n\n--- transcript ---\n" +
    JSON.stringify(result.transcript, null, 2);
}

function refreshSendButton() {
  const mw = selectedTarget();
  const hasMw = mw !== null;
  $("#send").disabled = !(currentTemplate && hasMw);
  $("#send").title = hasMw
    ? `Send the templated SapientMessage to ${mw.name} (${mw.host}:${mw.port})`
    : "Select a middleware in the Nodes drawer before sending";
  $("#run-flow").disabled = !(flowSteps.length && hasMw);
}

// Header toggle: drawer hidden/shown by `hidden` attribute, aria-expanded
// kept in sync for assistive tech and CSS targeting.
function toggleDrawer(toggleId, panelId) {
  return () => {
    const panel = $("#" + panelId);
    const btn = $("#" + toggleId);
    const open = panel.hidden;
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  };
}

// "ok" < "warn" < "fail" < "unknown". Unknown sorts last so an item we
// haven't observed yet is treated as worse than a known failure (same
// rule msf-nodes' aggregator uses on the backend).
const SEV_RANK = { ok: 0, warn: 1, fail: 2, unknown: 3 };
function worstSeverity(items, getter) {
  let worst = null;
  for (const it of items || []) {
    const sev = getter(it);
    if (sev == null) continue;
    if (worst == null || (SEV_RANK[sev] ?? 99) > (SEV_RANK[worst] ?? 99)) {
      worst = sev;
    }
  }
  return worst;
}
function applyToggleSeverity(toggleId, sev) {
  const btn = $("#" + toggleId);
  if (!btn) return;
  btn.classList.remove("status-ok", "status-warn", "status-fail", "status-unknown");
  if (sev) btn.classList.add(`status-${sev}`);
}

// (loadMiddlewares / renderMiddlewareList / commitMiddlewareEdit were
// removed when the Middleware drawer was folded into the unified Nodes
// drawer. The behaviour they covered — render rows, select a send
// target, PATCH host/port — now lives in loadNodes() / renderNodeList()
// below, keyed on entry.type instead of a separate state list.)

async function reloadFromDisk() {
  if (!currentTemplate) return;
  delete editBuffer[currentTemplate];
  const r = await fetch(`/api/templates/${encodeURIComponent(currentTemplate)}`);
  if (!r.ok) {
    $("#editor").value = `// load failed: ${r.status}`;
    return;
  }
  const data = await r.json();
  $("#editor").value = data.raw;
}

function buildSendBody() {
  const mw = selectedTarget();
  if (!mw) throw new Error("select a middleware first");
  return {
    host: mw.host,
    port: mw.port,
    node_id: ensureUUID(),
    validate_before_send: $("#validate-before").checked,
    steps: [{
      template_name: currentTemplate,
      raw_json: $("#editor").value,
      recv_timeout_s: Number($("#recv-timeout").value),
      drain_after_s: Number($("#drain-after").value),
    }],
  };
}

async function sendTemplate() {
  saveEndpoint();
  const body = buildSendBody();
  $("#send-status").textContent = "sending...";
  $("#send").disabled = true;
  try {
    const r = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      showError(err.detail || `HTTP ${r.status}`);
      return;
    }
    const result = await r.json();
    showFlowResult(result);
    await loadRecentRuns();
  } catch (exc) {
    showError(String(exc));
  } finally {
    $("#send").disabled = false;
    $("#send-status").textContent = "";
  }
}

async function validateOnly() {
  $("#send-status").textContent = "validating...";
  try {
    const r = await fetch("/api/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        node_id: $("#node-id").value.trim() || newUUID(),
        template_name: currentTemplate,
        raw_json: $("#editor").value,
      }),
    });
    const result = await r.json();
    const ve = $("#validation-errors");
    const sum = $("#result-summary");
    if (result.ok) {
      sum.className = "ok";
      sum.textContent = `validate: OK (${result.content})`;
      ve.textContent = "";
    } else {
      sum.className = "err";
      sum.textContent = `validate: ${result.errors.length} error(s)`;
      ve.innerHTML = result.errors.map((e) => `<div>• ${e}</div>`).join("");
    }
    $("#result-transcript").textContent = "";
  } catch (exc) {
    showError(String(exc));
  } finally {
    $("#send-status").textContent = "";
  }
}

async function regenerateTemplates() {
  const status = $("#regenerate-status");
  status.textContent = "building...";
  $("#regenerate").disabled = true;
  try {
    const r = await fetch("/api/templates/regenerate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (!r.ok) {
      status.textContent = `build failed: HTTP ${r.status}`;
      return;
    }
    const data = await r.json();
    status.textContent = `built ${data.count} templates`;
    for (const k of Object.keys(editBuffer)) delete editBuffer[k];
    await loadTemplates();
  } catch (exc) {
    status.textContent = `build failed: ${exc}`;
  } finally {
    $("#regenerate").disabled = false;
  }
}

async function clearTemplates() {
  if (!confirm("Delete every .json under templates/?\n\nThe sidebar will go empty. Click 'Build from .proto' to regenerate the canonical set, or drop your own .json into the mounted templates/ volume.")) {
    return;
  }
  const status = $("#regenerate-status");
  status.textContent = "clearing...";
  $("#clear-templates").disabled = true;
  try {
    const r = await fetch("/api/templates", { method: "DELETE" });
    if (!r.ok) {
      status.textContent = `clear failed: HTTP ${r.status}`;
      return;
    }
    const data = await r.json();
    status.textContent = `cleared ${data.count} templates`;
    for (const k of Object.keys(editBuffer)) delete editBuffer[k];
    currentTemplate = null;
    $("#editor").value = "";
    $("#editor-title").textContent = "";
    $("#validate-only").disabled = true;
    $("#reload-template").disabled = true;
    $("#result-summary").textContent = "No run yet.";
    $("#result-summary").className = "muted";
    $("#result-transcript").textContent = "";
    $("#validation-errors").innerHTML = "";
    await loadTemplates();
    refreshSendButton();
  } catch (exc) {
    status.textContent = `clear failed: ${exc}`;
  } finally {
    $("#clear-templates").disabled = false;
  }
}

async function clearRuns() {
  if (!confirm("Delete every run transcript under runs/?\n\nThis is destructive — the JSON files are the only record. (They're easy to regenerate by re-running a flow.)")) {
    return;
  }
  const status = $("#clear-runs-status");
  status.textContent = "clearing...";
  $("#clear-runs").disabled = true;
  try {
    const r = await fetch("/api/runs", { method: "DELETE" });
    if (!r.ok) {
      status.textContent = `clear failed: HTTP ${r.status}`;
      return;
    }
    const data = await r.json();
    status.textContent = `cleared ${data.count} runs`;
    await loadRecentRuns();
  } catch (exc) {
    status.textContent = `clear failed: ${exc}`;
  } finally {
    $("#clear-runs").disabled = false;
  }
}

function showError(msg) {
  const sum = $("#result-summary");
  sum.className = "err";
  sum.textContent = `error: ${msg}`;
  $("#result-transcript").textContent = "";
  $("#validation-errors").textContent = "";
}

function showResult(result) {
  const sum = $("#result-summary");
  const ve = $("#validation-errors");
  ve.innerHTML = "";
  const validation = result.validation_errors || [];
  if (validation.length && !result.transcript?.length) {
    sum.className = "err";
    sum.textContent = `validation failed (not sent): ${validation.length} error(s)`;
    ve.innerHTML = validation.map((e) => `<div>• ${e}</div>`).join("");
    $("#result-transcript").textContent = "";
    return;
  }
  if (validation.length) {
    ve.innerHTML = `<div class="warn">validation warnings (sent anyway):</div>` +
      validation.map((e) => `<div>• ${e}</div>`).join("");
  }
  const nrecv = (result.transcript || []).filter((t) => t.direction === "recv").length;
  if (result.error) {
    sum.className = "err";
    sum.textContent = `${result.run_id || ""} → ${result.error}`;
  } else if (nrecv > 0) {
    sum.className = "ok";
    sum.textContent = `${result.run_id} → sent ${result.template}, received ${nrecv} reply(ies)`;
  } else {
    sum.className = "warn";
    sum.textContent = `${result.run_id} → sent ${result.template}, no reply within window`;
  }
  $("#result-transcript").textContent = JSON.stringify(result.transcript, null, 2);
}

async function loadRecentRuns() {
  const r = await fetch("/api/runs");
  if (!r.ok) return;
  const runs = await r.json();
  const tbody = $("#recent-runs tbody");
  tbody.innerHTML = "";
  const countEl = $("#runs-count");
  if (countEl) countEl.textContent = runs.length ? `${runs.length} run(s) on disk` : "no runs yet";

  // Message-toggle severity reflects the most recent run: error → fail,
  // sent-but-no-reply → warn, success → ok, no runs ever → unknown.
  if (runs.length === 0) {
    applyToggleSeverity("message-toggle", "unknown");
  } else {
    const latest = runs[0];
    let sev = "ok";
    if (latest.error) sev = "fail";
    else if ((latest.recv_contents || []).length === 0) sev = "warn";
    applyToggleSeverity("message-toggle", sev);
  }
  for (const run of runs) {
    const tr = document.createElement("tr");
    tr.className = run.error ? "err" : "ok";
    const time   = run.started_utc?.slice(11,19) || "?";
    const target = `${run.host || "?"}:${run.port ?? "?"}`;
    const sentCell = `<span class="content">${run.sent_content || run.template || "—"}</span>` +
                     (run.sent_summary ? ` <span class="muted small">${run.sent_summary}</span>` : "");
    let resultCell;
    if (run.error) {
      resultCell = `<span class="muted">ERR</span> ${run.error}`;
    } else if ((run.recv_contents || []).length === 0) {
      resultCell = `<span class="muted">no reply</span>`;
    } else {
      resultCell = run.recv_contents.map((c, i) => {
        const sum = run.recv_summaries?.[i];
        return `<span class="content">${c}</span>` + (sum ? ` <span class="muted small">${sum}</span>` : "");
      }).join("<br>");
    }
    tr.innerHTML = `
      <td>${time}</td>
      <td>${run.template || ""}</td>
      <td>${sentCell}</td>
      <td>${resultCell}</td>
      <td><span class="muted small">${target}</span></td>`;
    tr.addEventListener("click", async () => {
      const r2 = await fetch(`/api/runs/${encodeURIComponent(run.run_id)}`);
      if (!r2.ok) return;
      const data = await r2.json();
      (data.kind === "flow" ? showFlowResult : showResult)(data);
    });
    tbody.appendChild(tr);
  }
}

// Refresh cadence for the Nodes + Services drawers.
const NODES_REFRESH_MS = 10000;
let nodesRefreshTimer = null;

// Services drawer state (the containers we spin: ui, gps, ntp, nodes,
// apex, cot-bridge). Filtered view of the same /api/nodes endpoint;
// status drives the header badge so a glance at the top of every page
// tells you whether the stack is healthy.
let serviceList = [];

async function loadServices() {
  let payload;
  try {
    const r = await fetch("/api/nodes?type=service");
    payload = r.ok ? await r.json() : { config_error: `HTTP ${r.status}`, nodes: [] };
  } catch (exc) {
    payload = { config_error: String(exc), nodes: [] };
  }
  serviceList = payload.nodes || [];

  const status = $("#services-status");
  if (payload.config_error) {
    status.textContent = `service: ${payload.config_error}`;
    status.className = "muted small err";
  } else if (serviceList.length === 0) {
    status.textContent = "no services configured";
    status.className = "muted small";
  } else {
    status.textContent = "";
    status.className = "muted small";
  }

  renderServiceList();
  applyToggleSeverity(
    "services-toggle",
    worstSeverity(serviceList, (n) => n.severity)
  );
}

function renderServiceList() {
  const list = $("#services-list");
  list.innerHTML = "";
  for (const s of serviceList) {
    const sev = s.severity || "unknown";
    const row = document.createElement("div");
    row.className = "service-row";
    const st = s.status || {};
    const rtt = st.rtt_s != null ? `${Math.round(st.rtt_s * 1000)} ms` : "—";
    const err = st.error ? ` · ${st.error}` : "";
    row.title = `${s.name}\n${s.host}:${s.port} (${s.probe_kind || "—"})\nrtt ${rtt}${err}`;
    row.innerHTML = `
      <span class="dot status-${sev}" aria-label="overall: ${sev}"></span>
      <span class="name">${s.name}</span>
      <code class="host">${s.host}:${s.port}</code>
      <span class="kind muted small">${s.probe_kind || "—"}</span>
    `;
    list.appendChild(row);
  }
}

// Per-node expandable details panels. Add a new entry here when another
// node type/name grows drilldown. Each `match` is given the node object;
// each `render` returns the HTML to inject under the row.
const NODE_EXPANDERS = [
  { match: (n) => n.name === "Apex Local", render: renderApexExpansion },
];

function expanderFor(node) {
  for (const e of NODE_EXPANDERS) if (e.match(node)) return e.render;
  return null;
}

async function renderApexExpansion(_node) {
  const [state, guiStat, sqlStat] = await Promise.all([
    fetch("/api/apex/state").then((r) => r.ok ? r.json() : { available: false, reason: `HTTP ${r.status}` }),
    fetch("/api/apex/gui/status").then((r) => r.ok ? r.json() : { running: false }),
    fetch("/api/apex/sqlite/status").then((r) => r.ok ? r.json() : { running: false, url: "" }),
  ]);
  const stateRow = state.available
    ? `<span class="dot status-ok"></span> healthy · ${state.connections_open} connections active`
    : `<span class="dot status-warn"></span> archive unavailable: ${state.reason || "?"}`;
  const recRow = state.available
    ? `<code>${state.file}</code> · ${state.messages} msgs · rolls daily`
    : `<span class="muted">—</span>`;
  const guiBtn = guiStat.running
    ? `<button class="apex-btn" data-action="gui-stop">Stop Apex GUI</button>`
    : `<button class="apex-btn" data-action="gui-start">Open Apex GUI</button>`;
  const sqlBtn = sqlStat.running
    ? `<button class="apex-btn" data-action="sqlite-stop">Stop Apex SQLite</button>`
    : `<button class="apex-btn" data-action="sqlite-start">Open Apex SQLite</button>`;
  const sqlFrame = sqlStat.running
    ? `<iframe class="apex-sqlite-frame" src="${sqlStat.url}" title="apex archive (sqlite-web)"></iframe>`
    : ``;
  return `
    <div class="kv"><span>status</span><span>${stateRow}</span></div>
    <div class="kv"><span>recording</span><span>${recRow}</span></div>
    <div class="apex-actions">${guiBtn}${sqlBtn}</div>
    ${sqlFrame}
  `;
}

// Click handlers for action buttons inside an Apex expansion panel. The
// panel itself re-renders fresh on each toggle, so we delegate on the
// list container — works for newly-inserted panels too.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".apex-btn");
  if (!btn) return;
  const action = btn.dataset.action;
  const panel = btn.closest(".node-row-details");
  const row   = panel ? panel.previousElementSibling : null;
  if (!panel || !row) return;
  btn.disabled = true;
  btn.textContent = "…";
  try {
    if (action === "gui-start")    await fetch("/api/apex/gui/start",    { method: "POST" });
    if (action === "gui-stop")     await fetch("/api/apex/gui/stop",     { method: "POST" });
    if (action === "sqlite-start") await fetch("/api/apex/sqlite/start", { method: "POST" });
    if (action === "sqlite-stop")  await fetch("/api/apex/sqlite/stop",  { method: "POST" });
  } catch (exc) {
    btn.textContent = `err: ${exc}`;
    return;
  }
  // Re-render the panel against fresh state.
  const node = nodeList.find((x) => x.id === row.dataset.id);
  if (node) panel.innerHTML = await renderApexExpansion(node);
});

// Per-session memory of which node rows are expanded. Re-applied after
// every renderNodeList() so polling-driven re-renders don't blow away
// the operator's open panels (or their iframes).
const expandedNodeIds = new Set();

async function toggleNodeExpand(row, node) {
  const next = row.nextElementSibling;
  if (next && next.classList.contains("node-row-details")) {
    next.remove();
    row.classList.remove("expanded");
    expandedNodeIds.delete(node.id);
    return;
  }
  const render = expanderFor(node);
  if (!render) return;
  expandedNodeIds.add(node.id);
  const panel = document.createElement("div");
  panel.className = "node-row-details";
  panel.dataset.id = node.id;
  panel.innerHTML = `<div class="muted small">loading…</div>`;
  row.after(panel);
  row.classList.add("expanded");
  panel.innerHTML = await render(node);
}

// Captured before each renderNodeList() wipe and re-attached after, so
// poll-driven re-renders don't reload iframes inside expanded panels.
// Key = node id, value = the live <div.node-row-details> DOM node.
let _capturedPanels = new Map();

function captureExpandedPanels() {
  _capturedPanels = new Map();
  const list = $("#nodes-list");
  list.querySelectorAll(".node-row-details").forEach((panel) => {
    if (panel.dataset.id) _capturedPanels.set(panel.dataset.id, panel);
  });
}

async function restoreExpandedNodes() {
  if (expandedNodeIds.size === 0) { _capturedPanels.clear(); return; }
  const list = $("#nodes-list");
  for (const id of expandedNodeIds) {
    const row = list.querySelector(`.node-row[data-id="${id}"]`);
    const node = nodeList.find((x) => x.id === id);
    if (!row || !node) { expandedNodeIds.delete(id); continue; }
    const render = expanderFor(node);
    if (!render) { expandedNodeIds.delete(id); continue; }
    row.classList.add("expanded");
    const captured = _capturedPanels.get(id);
    if (captured) {
      // Re-attach the SAME DOM node — iframe inside keeps its document,
      // no reload, no flicker. Stats stay as they were until the user
      // clicks something that re-renders explicitly.
      row.after(captured);
    } else {
      // First expand or panel was removed — render fresh.
      const panel = document.createElement("div");
      panel.className = "node-row-details";
      panel.dataset.id = id;
      panel.innerHTML = `<div class="muted small">loading…</div>`;
      row.after(panel);
      panel.innerHTML = await render(node);
    }
  }
  _capturedPanels.clear();
}

async function loadNodes() {
  // Unified drawer: every non-service entry. We rely on the nodes
  // service's /api/nodes?type=… filter; doing two filtered fetches keeps
  // this synced with the service-side typing rather than reproducing
  // type lists client-side.
  const platform = await _fetchByType("platform-node");
  const middleware = await _fetchByType("middleware");
  const tak = await _fetchByType("tak-server");
  nodeList = [...platform.nodes, ...middleware.nodes, ...tak.nodes];

  const cfgErr = platform.config_error || middleware.config_error || tak.config_error;
  const status = $("#nodes-status");
  if (cfgErr) {
    status.textContent = `service: ${cfgErr}`;
    status.className = "muted small err";
  } else if (nodeList.length === 0) {
    status.textContent = "no nodes configured — click + Add";
    status.className = "muted small";
  } else {
    status.textContent = `${nodeList.length} node${nodeList.length === 1 ? "" : "s"}`;
    status.className = "muted small";
  }

  // Default the send-target selection: prefer the saved id if it still
  // matches a middleware-type row; else first-OK middleware; else first
  // middleware; else null.
  const middlewares = nodeList.filter((n) => n.type === "middleware");
  if (selectedTargetId && !middlewares.find((m) => m.id === selectedTargetId)) {
    selectedTargetId = null;
  }
  if (!selectedTargetId && middlewares.length) {
    const firstOk = middlewares.find((m) => m.severity === "ok");
    selectedTargetId = (firstOk || middlewares[0]).id;
    saveEndpoint();
  }

  captureExpandedPanels();
  renderNodeList();
  restoreExpandedNodes();
  refreshSendButton();
  applyToggleSeverity(
    "nodes-toggle",
    worstSeverity(
      // Skip entries deliberately not probed: middleware with probe:false,
      // and tak-server entries without an admin_port (UDP-only by design,
      // always unknown). Otherwise the badge would be stuck at warn/unknown.
      nodeList.filter((n) => {
        if (n.type === "middleware" && n.probe === false) return false;
        if (n.type === "tak-server" && n.probe_kind !== "tcp") return false;
        return true;
      }),
      (n) => n.severity,
    ),
  );
}

async function _fetchByType(type) {
  try {
    const r = await fetch(`/api/nodes?type=${encodeURIComponent(type)}`);
    if (!r.ok) return { config_error: `HTTP ${r.status}`, nodes: [] };
    return await r.json();
  } catch (exc) {
    return { config_error: String(exc), nodes: [] };
  }
}

function _platformNodeServicesTooltip(n) {
  const lines = [`${n.name} · ${n.host}`];
  for (const [kind, svc] of Object.entries(n.services || {})) {
    const sev = svc.severity || "unknown";
    if (kind === "ntp") {
      const off = svc.offset_s != null ? ` offset=${(svc.offset_s * 1000).toFixed(0)}ms` : "";
      lines.push(`  ntp: ${sev}${off}${svc.error ? " · " + svc.error : ""}`);
    } else if (kind === "gps") {
      const sats = svc.satellites != null ? ` sats=${svc.satellites}` : "";
      const age  = svc.age_s != null ? ` age=${svc.age_s.toFixed(1)}s` : "";
      lines.push(`  gps: ${sev}${sats}${age}${svc.error ? " · " + svc.error : ""}`);
    } else {
      lines.push(`  ${kind}: ${sev}${svc.error ? " · " + svc.error : ""}`);
    }
  }
  return lines.join("\n");
}

function _middlewareTooltip(n) {
  const s = n.status || {};
  const rtt = s.rtt_s != null ? `${Math.round(s.rtt_s * 1000)} ms` : "—";
  const err = s.error ? ` · ${s.error}` : "";
  return `${n.name}\n${n.host}:${n.port} (${n.kind || "—"})\nrtt ${rtt}${err}`;
}

function renderNodeList() {
  const list = $("#nodes-list");
  list.innerHTML = "";

  for (const n of nodeList) {
    const sev = n.severity || "unknown";
    const isSelectable = n.type === "middleware";
    const isSelected = isSelectable && n.id === selectedTargetId;

    const row = document.createElement("div");
    row.className = "node-row " + n.type + (isSelected ? " active" : "");
    row.dataset.id = n.id;
    row.dataset.type = n.type;

    let secondaryHtml = "";
    let titleStr = "";
    if (n.type === "platform-node") {
      const chips = Object.entries(n.services || {}).map(([kind, svc]) => {
        const sub = (svc && svc.severity) || "unknown";
        return `<span class="svc"><span class="dot status-${sub}"></span>${kind}</span>`;
      }).join("");
      secondaryHtml = `<span class="svcs">${chips}</span>`;
      titleStr = _platformNodeServicesTooltip(n);
    } else if (n.type === "middleware") {
      // The `probe` flag is still editable in the modal, but we don't
      // surface it in the row — it's noise for the common case (probe
      // on), and the dot already reflects status correctly.
      secondaryHtml = `<span class="kind muted small">${n.kind || "—"}</span>`;
      titleStr = _middlewareTooltip(n);
    } else if (n.type === "tak-server") {
      const proto = (n.protocol || "udp").toUpperCase();
      const s = n.status || {};
      secondaryHtml = `<span class="kind muted small">${proto}</span>`;
      titleStr = `${n.name}\n${n.host}:${n.port} (${proto})` +
                 (s.error ? `\n${s.error}` : "");
    } else {
      secondaryHtml = `<span class="muted small">${n.type}</span>`;
      titleStr = `${n.name} · ${n.host}${n.port ? `:${n.port}` : ""}`;
    }
    row.title = titleStr;

    const radioCell = isSelectable
      ? `<input type="radio" name="target" value="${n.id}"${isSelected ? " checked" : ""}>`
      : `<span class="radio-placeholder" aria-hidden="true"></span>`;

    const chev = expanderFor(n) ? `<span class="chev" aria-hidden="true">▸</span>` : "";

    row.innerHTML = `
      <span class="dot status-${sev}" aria-label="overall: ${sev}"></span>
      ${radioCell}
      <span class="name">${chev}${n.name}</span>
      <code class="host">${n.host}${n.port ? ":" + n.port : ""}</code>
      <span class="type-badge type-${n.type}">${n.type}</span>
      ${secondaryHtml}
      <span class="row-actions">
        <button class="ghost row-edit"   data-id="${n.id}" title="Edit node">edit</button>
        <button class="ghost row-delete" data-id="${n.id}" title="Delete node">×</button>
      </span>
    `;
    list.appendChild(row);
  }

  // Row-level click → select (middleware) AND toggle expand (any node
  // with a registered expander). Inputs and action buttons handle their
  // own clicks; don't double-fire.
  list.querySelectorAll(".node-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.matches("input, button")) return;
      const n = nodeList.find((x) => x.id === row.dataset.id);
      if (!n) return;
      if (row.classList.contains("middleware")) {
        selectedTargetId = row.dataset.id;
        saveEndpoint();
        list.querySelectorAll(".node-row.middleware").forEach((r) => {
          r.classList.toggle("active", r.dataset.id === selectedTargetId);
          const rb = r.querySelector('input[type="radio"]');
          if (rb) rb.checked = (r.dataset.id === selectedTargetId);
        });
        refreshSendButton();
      }
      if (expanderFor(n)) toggleNodeExpand(row, n);
    });
  });

  list.querySelectorAll(".row-edit").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const n = nodeList.find((x) => x.id === btn.dataset.id);
      if (n) openNodeForm(n);
    });
  });
  list.querySelectorAll(".row-delete").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteNode(btn.dataset.id);
    });
  });
}

// ----------------------------------------------------------- CRUD: modal

function openNodeForm(existing) {
  const modal = $("#node-modal");
  const form = $("#node-form");
  form.reset();
  $("#node-form-error").textContent = "";
  if (existing) {
    $("#node-form-title").textContent = `Edit ${existing.name}`;
    form.elements.id.value = existing.id;
    form.elements.id.disabled = true;
    form.elements.type.value = existing.type;
    form.elements.type.disabled = true;
    form.elements.name.value = existing.name || "";
    form.elements.host.value = existing.host || "";
    form.elements.port.value = existing.port ?? "";
    form.elements.description.value = existing.description || "";
    if (existing.type === "platform-node") {
      const wanted = new Set(existing.services_enabled || existing.services || []);
      form.querySelectorAll('input[name="services"]').forEach((cb) => {
        cb.checked = wanted.has(cb.value);
      });
    } else if (existing.type === "middleware") {
      form.elements.kind.value = existing.kind || "";
      form.elements.probe.checked = existing.probe !== false;
    }
    form.dataset.mode = "edit";
    form.dataset.editId = existing.id;
  } else {
    $("#node-form-title").textContent = "Add Node";
    form.elements.id.disabled = false;
    form.elements.type.disabled = false;
    form.dataset.mode = "create";
    delete form.dataset.editId;
  }
  _updateFormTypeVisibility(form.elements.type.value);
  modal.hidden = false;
}

function closeNodeForm() {
  $("#node-modal").hidden = true;
}

function _updateFormTypeVisibility(type) {
  $("#node-form").querySelectorAll(".platform-only").forEach((el) => {
    el.style.display = (type === "platform-node") ? "" : "none";
  });
  $("#node-form").querySelectorAll(".middleware-only").forEach((el) => {
    el.style.display = (type === "middleware") ? "" : "none";
  });
}

async function submitNodeForm(e) {
  e.preventDefault();
  const form = $("#node-form");
  const mode = form.dataset.mode;
  const errEl = $("#node-form-error");
  errEl.textContent = "";

  const body = {};
  const ports = form.elements.port.value;
  if (mode === "create") {
    body.id = form.elements.id.value.trim();
    body.type = form.elements.type.value;
  }
  body.name = form.elements.name.value.trim();
  body.host = form.elements.host.value.trim();
  if (ports) body.port = Number(ports);
  const desc = form.elements.description.value.trim();
  if (desc) body.description = desc;

  const type = mode === "create" ? body.type : form.elements.type.value;
  if (type === "platform-node") {
    body.services = Array.from(form.querySelectorAll('input[name="services"]:checked'))
                         .map((cb) => cb.value);
  } else if (type === "middleware") {
    const kind = form.elements.kind.value.trim();
    if (kind) body.kind = kind;
    body.probe = !!form.elements.probe.checked;
  }

  const submit = $("#node-form-submit");
  submit.disabled = true;
  try {
    const url = mode === "edit"
      ? `/api/nodes/${encodeURIComponent(form.dataset.editId)}`
      : "/api/nodes";
    const method = mode === "edit" ? "PATCH" : "POST";
    if (mode === "edit") delete body.id;  // immutable; not in PATCH payload
    const r = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      errEl.textContent = err.detail || `HTTP ${r.status}`;
      return;
    }
    closeNodeForm();
    await loadNodes();
  } catch (exc) {
    errEl.textContent = String(exc);
  } finally {
    submit.disabled = false;
  }
}

async function deleteNode(nodeId) {
  if (!confirm(`Delete node "${nodeId}"? This removes it from nodes.json — bring it back by re-adding or restoring the file.`)) {
    return;
  }
  try {
    const r = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`, { method: "DELETE" });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      alert(`Delete failed: ${err.detail || r.status}`);
      return;
    }
    if (selectedTargetId === nodeId) {
      selectedTargetId = null;
      saveEndpoint();
    }
    await loadNodes();
  } catch (exc) {
    alert(`Delete failed: ${exc}`);
  }
}

// ---------- Tests drawer ---------------------------------------------------
// Drives the regression service (long-running pytest wrapper on :8094)
// through the UI's proxy endpoints under /api/regression/*. Renders one
// row per test file with a green/yellow/red dot reflecting that file's
// outcome.

let _testsPollTimer = null;

async function refreshTestsResult() {
  try {
    const [status, result] = await Promise.all([
      fetchJSON("/api/regression/status"),
      fetchJSON("/api/regression/result"),
    ]);
    renderTests(status, result);
  } catch (exc) {
    $("#tests-status").textContent = `regression unreachable: ${exc}`;
    applyToggleSeverity("tests-toggle", "unknown");
  }
}

async function runTests() {
  const btn = $("#tests-run");
  btn.disabled = true;
  $("#tests-status").textContent = "starting…";
  applyToggleSeverity("tests-toggle", "unknown");
  try {
    const r = await fetchJSON("/api/regression/run", { method: "POST" });
    if (r.__status_code && r.__status_code >= 400 && r.__status_code !== 409) {
      $("#tests-status").textContent = r.detail || r.error || "failed to start";
      btn.disabled = false;
      return;
    }
    // Poll status every 1s until done.
    if (_testsPollTimer) clearInterval(_testsPollTimer);
    _testsPollTimer = setInterval(async () => {
      const st = await fetchJSON("/api/regression/status");
      if (st.status === "done") {
        clearInterval(_testsPollTimer);
        _testsPollTimer = null;
        const result = await fetchJSON("/api/regression/result");
        renderTests(st, result);
        btn.disabled = false;
      } else {
        const elapsed = st.started_at ? (Date.now() / 1000 - st.started_at).toFixed(1) : "?";
        $("#tests-status").textContent = `running… ${elapsed}s`;
      }
    }, 1000);
  } catch (exc) {
    $("#tests-status").textContent = `error: ${exc}`;
    btn.disabled = false;
  }
}

function renderTests(state, result) {
  const tbody = $("#tests-table tbody");
  tbody.innerHTML = "";
  const files = (result && result.available && result.per_file) || [];
  for (const f of files) {
    const tr = document.createElement("tr");
    tr.className = `test-row sev-${f.status}`;
    tr.innerHTML = `
      <td><span class="dot dot-${f.status}"></span>${labelFor(f.status)}</td>
      <td class="mono">${escapeHtml(f.file)}</td>
      <td class="num">${f.passed}</td>
      <td class="num">${f.failed}</td>
      <td class="num">${f.skipped}</td>`;
    tbody.appendChild(tr);
  }

  const overall = $("#tests-overall");
  const statusEl = $("#tests-status");
  if (state && state.status === "running") {
    statusEl.textContent = "running…";
    overall.textContent = "";
    overall.className = "tests-overall";
    applyToggleSeverity("tests-toggle", "unknown");
  } else if (result && result.available) {
    const t = result.totals || {passed:0,failed:0,skipped:0};
    const sev = result.overall_status || "unknown";
    statusEl.textContent =
      `last run: ${labelFor(sev)} — ${t.passed} passed, ${t.failed} failed, ${t.skipped} skipped` +
      (state && state.duration_s != null ? ` in ${state.duration_s}s` : "");
    overall.textContent = labelFor(sev);
    overall.className = `tests-overall sev-${sev}`;
    applyToggleSeverity("tests-toggle", sev);
  } else {
    statusEl.textContent = "no runs yet — click Run";
    overall.textContent = "";
    overall.className = "tests-overall";
    applyToggleSeverity("tests-toggle", "unknown");
  }

  const tail = $("#tests-tail");
  if (state && state.tail) {
    tail.hidden = false;
    tail.querySelector("pre").textContent = state.tail;
  } else {
    tail.hidden = true;
  }
}

function labelFor(sev) {
  return ({ok: "OK", warn: "WARN", fail: "FAIL", unknown: "—"}[sev] || sev);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}

async function fetchJSON(url, opts = {}) {
  const r = await fetch(url, opts);
  return r.json();
}

function init() {
  const saved = loadEndpoint();
  selectedTargetId = saved.target_node_id || null;
  $("#node-id").value = saved.node_id || newUUID();
  if (saved.recv_timeout_s != null) $("#recv-timeout").value = saved.recv_timeout_s;
  if (saved.drain_after_s != null) $("#drain-after").value = saved.drain_after_s;
  $("#validate-before").checked = !!saved.validate_before_send;
  $("#auto-new-uuid").checked = saved.auto_new_uuid !== false;  // default ON

  $("#new-uuid").addEventListener("click", () => { $("#node-id").value = newUUID(); saveEndpoint(); });
  $("#send").addEventListener("click", sendTemplate);
  $("#validate-only").addEventListener("click", validateOnly);
  $("#reload-template").addEventListener("click", reloadFromDisk);
  $("#regenerate").addEventListener("click", regenerateTemplates);
  $("#clear-templates").addEventListener("click", clearTemplates);
  $("#refresh-runs")?.addEventListener("click", loadRecentRuns);
  $("#clear-runs")?.addEventListener("click", clearRuns);

  // Header toggles for Nodes / Services / Message. Click to expand or
  // collapse the corresponding drawer; each toggle's coloured dot
  // reflects worst-of severity (Nodes / Services) or last-run status
  // (Message), and stays accurate even while the drawer is closed.
  $("#nodes-toggle").addEventListener("click", toggleDrawer("nodes-toggle", "nodes-panel"));
  $("#services-toggle").addEventListener("click", toggleDrawer("services-toggle", "services-panel"));
  $("#message-toggle").addEventListener("click", toggleDrawer("message-toggle", "message-panel"));
  $("#tests-toggle").addEventListener("click", () => {
    toggleDrawer("tests-toggle", "tests-panel")();
    // Fetch the last result whenever the drawer opens.
    if (!$("#tests-panel").hidden) refreshTestsResult();
  });
  $("#tests-run").addEventListener("click", runTests);

  // Nodes CRUD wiring.
  $("#add-node").addEventListener("click", () => openNodeForm(null));
  $("#node-form").addEventListener("submit", submitNodeForm);
  $("#node-modal").addEventListener("click", (e) => {
    if (e.target.dataset && e.target.dataset.dismiss === "modal") closeNodeForm();
  });
  $("#node-form").elements.type.addEventListener("change", (e) => {
    _updateFormTypeVisibility(e.target.value);
  });

  $("#mode-single").addEventListener("click", () => setMode("single"));
  $("#mode-flow").addEventListener("click", () => setMode("flow"));
  $("#run-flow").addEventListener("click", runFlow);
  $("#clear-flow").addEventListener("click", () => { flowSteps = []; renderFlow(); });
  $("#preset-reg-status").addEventListener("click", () => {
    flowSteps = [];
    addFlowStep("registration");
    addFlowStep("status_report");
  });
  $("#preset-reg-status-det").addEventListener("click", () => {
    flowSteps = [];
    addFlowStep("registration");
    addFlowStep("status_report");
    addFlowStep("detection_report");
  });
  renderFlow();
  ["node-id","recv-timeout","drain-after"].forEach((id) => {
    $("#" + id).addEventListener("change", saveEndpoint);
  });
  $("#validate-before").addEventListener("change", saveEndpoint);
  $("#auto-new-uuid").addEventListener("change", saveEndpoint);
  refreshSendButton();

  loadNodes();
  loadServices();
  loadTemplates();
  loadRecentRuns();
  // Surface the last regression result's status on the Tests toggle dot
  // even before the user opens the drawer.
  refreshTestsResult();

  if (nodesRefreshTimer) clearInterval(nodesRefreshTimer);
  nodesRefreshTimer = setInterval(() => {
    loadNodes();
    loadServices();
  }, NODES_REFRESH_MS);
}

document.addEventListener("DOMContentLoaded", init);
