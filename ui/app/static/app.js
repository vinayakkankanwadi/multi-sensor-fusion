"use strict";

const $ = (sel) => document.querySelector(sel);

// v6 = node selection persisted alongside middleware selection. Nothing
//      uses the selected node yet, but the row pattern matches Middleware
//      and the choice survives reloads.
const STORE_KEY = "msf_endpoint_v6";

function loadEndpoint() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
  catch { return {}; }
}
function saveEndpoint() {
  const data = {
    middleware_id: selectedMiddlewareId,
    node_id_selection: selectedNodeId,
    node_id: $("#node-id").value.trim(),
    recv_timeout_s: Number($("#recv-timeout").value),
    drain_after_s: Number($("#drain-after").value),
    validate_before_send: $("#validate-before").checked,
    auto_new_uuid: $("#auto-new-uuid").checked,
  };
  localStorage.setItem(STORE_KEY, JSON.stringify(data));
}

// Middleware registry state, refreshed every MW_REFRESH_MS.
let middlewareList = [];      // [{id, name, host, port, kind, status, ...}]
let selectedMiddlewareId = null;
let selectedNodeId = null;    // nodes are selectable too (cosmetic today)
const MW_REFRESH_MS = 10000;
let mwRefreshTimer = null;

function selectedMiddleware() {
  return middlewareList.find((m) => m.id === selectedMiddlewareId) || null;
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
    selectTemplate(templates[0].name);
  } else if (templates.find((t) => t.name === currentTemplate)) {
    selectTemplate(currentTemplate);
  }
}

let mode = "single";  // "single" or "flow"
let flowSteps = [];   // [{template_name, wait_for, recv_timeout_s, drain_after_s}]

async function selectTemplate(name) {
  if (mode === "flow") {
    addFlowStep(name);
    return;
  }
  currentTemplate = name;
  document.querySelectorAll("#template-list li").forEach((li) => {
    li.classList.toggle("active", li.dataset.name === name);
  });
  $("#editor-title").textContent = name;
  await reloadFromDisk();
  $("#validate-only").disabled = false;
  $("#reload-template").disabled = false;
  refreshSendButton();
}

function setMode(newMode) {
  mode = newMode;
  $("#mode-single").classList.toggle("active", mode === "single");
  $("#mode-flow").classList.toggle("active", mode === "flow");
  $("#single-pane").hidden = mode !== "single";
  $("#flow-pane").hidden = mode !== "flow";
  // Highlight sidebar items differently in flow mode (click = add).
  document.querySelectorAll("#template-list li").forEach((li) => {
    li.title = mode === "flow"
      ? "click to ADD as the next flow step"
      : "click to load into the editor";
  });
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
  const mw = selectedMiddleware();
  if (!mw) {
    $("#flow-status").textContent = "select a middleware first";
    return;
  }
  saveEndpoint();
  $("#flow-status").textContent = "running flow...";
  $("#run-flow").disabled = true;
  try {
    const body = {
      host: mw.host,
      port: mw.port,
      node_id: ensureUUID(),
      validate_before_send: $("#validate-before").checked,
      steps: flowSteps.map((s) => ({
        template_name: s.template_name,
        wait_for: s.wait_for || null,
        recv_timeout_s: s.recv_timeout_s,
        drain_after_s: s.drain_after_s,
      })),
    };
    const r = await fetch("/api/send_flow", {
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
  const mw = selectedMiddleware();
  const hasMw = mw !== null;
  $("#send").disabled = !(currentTemplate && hasMw);
  $("#send").title = hasMw
    ? `Send the templated SapientMessage to ${mw.name} (${mw.host}:${mw.port})`
    : "Select a middleware above before sending";
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

async function loadMiddlewares() {
  let payload;
  try {
    const r = await fetch("/api/middlewares");
    payload = r.ok ? await r.json() : { config_error: `HTTP ${r.status}`, middlewares: [] };
  } catch (exc) {
    payload = { config_error: String(exc), middlewares: [] };
  }
  middlewareList = payload.middlewares || [];

  const status = $("#middleware-status");
  if (payload.config_error) {
    status.textContent = `service: ${payload.config_error}`;
    status.className = "muted small err";
  } else if (middlewareList.length === 0) {
    status.textContent = "no middlewares configured";
    status.className = "muted small";
  } else {
    status.textContent = "";
    status.className = "muted small";
  }

  if (selectedMiddlewareId && !middlewareList.find((m) => m.id === selectedMiddlewareId)) {
    selectedMiddlewareId = null;
  }
  if (!selectedMiddlewareId && middlewareList.length) {
    const firstOk = middlewareList.find((m) => m.status && m.status.ok);
    selectedMiddlewareId = (firstOk || middlewareList[0]).id;
    saveEndpoint();
  }

  renderMiddlewareList();
  refreshSendButton();
  // Header badge colour: worst across the *probed* middlewares (skip
  // entries we deliberately don't probe — they'd always be "unknown"
  // and would drag the badge yellow forever).
  applyToggleSeverity(
    "middleware-toggle",
    worstSeverity(middlewareList.filter((m) => m.probe !== false),
                  (m) => (m.status || {}).severity)
  );
}

function renderMiddlewareList() {
  const list = $("#middleware-list");
  // Preserve focus / cursor on the input the user is currently editing,
  // so the periodic refresh doesn't yank them out mid-type.
  const active = document.activeElement;
  const activeId = active && active.dataset ? active.dataset.id : null;
  const activeField = active && active.dataset ? active.dataset.field : null;
  const cursor = active && active.selectionStart != null ? active.selectionStart : null;

  list.innerHTML = "";
  for (const m of middlewareList) {
    const sev = (m.status && m.status.severity) || "unknown";
    const row = document.createElement("label");
    row.className = "middleware-row" + (m.id === selectedMiddlewareId ? " active" : "");
    row.dataset.id = m.id;
    const rtt = m.status && m.status.rtt_s != null
      ? `${Math.round(m.status.rtt_s * 1000)} ms`
      : "—";
    const err = m.status && m.status.error ? ` (${m.status.error})` : "";
    row.title = `${m.kind} · rtt ${rtt}${err}`;
    row.innerHTML = `
      <span class="dot status-${sev}" aria-label="status: ${sev}"></span>
      <input type="radio" name="mw" value="${m.id}"${m.id === selectedMiddlewareId ? " checked" : ""}>
      <span class="name">${m.name}</span>
      <input type="text"   class="mw-host" data-id="${m.id}" data-field="host" value="${m.host}" spellcheck="false">
      <input type="number" class="mw-port" data-id="${m.id}" data-field="port" min="1" max="65535" value="${m.port}">
    `;
    list.appendChild(row);
  }

  // Select on radio click or clicking the row itself (but not the inputs).
  list.querySelectorAll(".middleware-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.matches("input.mw-host, input.mw-port")) return;
      selectedMiddlewareId = row.dataset.id;
      saveEndpoint();
      list.querySelectorAll(".middleware-row").forEach((r) => {
        r.classList.toggle("active", r.dataset.id === selectedMiddlewareId);
        const rb = r.querySelector('input[type="radio"]');
        if (rb) rb.checked = (r.dataset.id === selectedMiddlewareId);
      });
      refreshSendButton();
    });
  });

  // Persist edits when the user commits (blur or Enter), with light
  // debounce so they can finish typing first.
  list.querySelectorAll(".mw-host, .mw-port").forEach((el) => {
    el.addEventListener("change", () => commitMiddlewareEdit(el));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); el.blur(); }
    });
  });

  // Restore the user's editing focus if a refresh fired while they typed.
  if (activeId && activeField) {
    const sel = `.middleware-row[data-id="${activeId}"] [data-field="${activeField}"]`;
    const el = list.querySelector(sel);
    if (el) {
      el.focus();
      if (cursor != null && el.setSelectionRange) {
        try { el.setSelectionRange(cursor, cursor); } catch {}
      }
    }
  }
}

async function commitMiddlewareEdit(el) {
  const id = el.dataset.id;
  const field = el.dataset.field;
  const value = el.value.trim();
  const m = middlewareList.find((x) => x.id === id);
  if (!m) return;

  let body;
  if (field === "host") {
    if (!value || value === m.host) return;
    body = { host: value };
  } else if (field === "port") {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 1 || n > 65535 || n === m.port) return;
    body = { port: n };
  } else {
    return;
  }

  const status = $("#middleware-status");
  status.textContent = `saving ${field}…`;
  status.className = "muted small";
  el.classList.add("saving");
  try {
    const r = await fetch(`/api/middlewares/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      status.textContent = `save failed: ${err.detail || r.status}`;
      status.className = "muted small err";
      el.value = String(m[field]); // revert on failure
      return;
    }
    const updated = await r.json();
    // Patch in-place so the next refresh sees current values; reload to
    // pick up the fresh status from the post-edit re-probe.
    Object.assign(m, updated);
    status.textContent = `${m.name}: ${field} updated`;
    setTimeout(() => loadMiddlewares(), 200);
  } catch (exc) {
    status.textContent = `save failed: ${exc}`;
    status.className = "muted small err";
    el.value = String(m[field]);
  } finally {
    el.classList.remove("saving");
  }
}

async function reloadFromDisk() {
  if (!currentTemplate) return;
  const r = await fetch(`/api/templates/${encodeURIComponent(currentTemplate)}`);
  if (!r.ok) {
    $("#editor").value = `// load failed: ${r.status}`;
    return;
  }
  const data = await r.json();
  $("#editor").value = data.raw;
}

function buildSendBody() {
  const mw = selectedMiddleware();
  if (!mw) throw new Error("select a middleware first");
  return {
    host: mw.host,
    port: mw.port,
    node_id: ensureUUID(),
    template_name: currentTemplate,
    raw_json: $("#editor").value,
    recv_timeout_s: Number($("#recv-timeout").value),
    drain_after_s: Number($("#drain-after").value),
    validate_before_send: $("#validate-before").checked,
  };
}

async function sendTemplate() {
  saveEndpoint();
  const body = buildSendBody();
  $("#send-status").textContent = "sending...";
  $("#send").disabled = true;
  try {
    const r = await fetch("/api/send", {
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
    showResult(result);
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
      if (r2.ok) showResult(await r2.json());
    });
    tbody.appendChild(tr);
  }
}

// Platform-node picker — replaces the old "clocks" panel. msf-nodes
// composes NTP + GPS health per configured upstream host and we just
// render the rolled-up dot here. Refresh cadence kept short (10 s) so
// the dot tracks reality without the user having to refresh.

const NODES_REFRESH_MS = 10000;
let nodeList = [];
let nodesRefreshTimer = null;

async function loadNodes() {
  let payload;
  try {
    // Filtered view: the Nodes drawer renders platform-nodes only. The
    // Middleware drawer reads /api/middlewares (a separate filtered view
    // backed by the same service) so the two row layouts stay distinct.
    const r = await fetch("/api/nodes?type=platform-node");
    payload = r.ok ? await r.json() : { config_error: `HTTP ${r.status}`, nodes: [] };
  } catch (exc) {
    payload = { config_error: String(exc), nodes: [] };
  }
  nodeList = payload.nodes || [];

  const status = $("#nodes-status");
  if (payload.config_error) {
    status.textContent = `service: ${payload.config_error}`;
    status.className = "muted small err";
  } else if (nodeList.length === 0) {
    status.textContent = "no nodes configured";
    status.className = "muted small";
  } else {
    status.textContent = "";
    status.className = "muted small";
  }

  renderNodeList();
  applyToggleSeverity(
    "nodes-toggle",
    worstSeverity(nodeList, (n) => n.severity)
  );
}

function nodeTooltip(n) {
  const lines = [`${n.name} · ${n.host}`];
  for (const [kind, svc] of Object.entries(n.services || {})) {
    const sev = svc.severity || "unknown";
    if (kind === "ntp") {
      const off = svc.offset_s != null ? ` offset=${(svc.offset_s * 1000).toFixed(0)}ms` : "";
      const err = svc.error ? ` · ${svc.error}` : "";
      lines.push(`  ntp: ${sev}${off}${err}`);
    } else if (kind === "gps") {
      const sats = svc.satellites != null ? ` sats=${svc.satellites}` : "";
      const age  = svc.age_s != null ? ` age=${svc.age_s.toFixed(1)}s` : "";
      const err = svc.error ? ` · ${svc.error}` : "";
      lines.push(`  gps: ${sev}${sats}${age}${err}`);
    } else {
      lines.push(`  ${kind}: ${sev}${svc.error ? " · " + svc.error : ""}`);
    }
  }
  return lines.join("\n");
}

function renderNodeList() {
  const list = $("#nodes-list");
  list.innerHTML = "";

  // Default the selection: keep what was saved if still present, else
  // first-OK, else first. Keeps something always selected once nodes are
  // configured.
  if (selectedNodeId && !nodeList.find((n) => n.id === selectedNodeId)) {
    selectedNodeId = null;
  }
  if (!selectedNodeId && nodeList.length) {
    const firstOk = nodeList.find((n) => n.severity === "ok");
    selectedNodeId = (firstOk || nodeList[0]).id;
    saveEndpoint();
  }

  for (const n of nodeList) {
    const sev = n.severity || "unknown";
    const row = document.createElement("label");
    row.className = "node-row" + (n.id === selectedNodeId ? " active" : "");
    row.dataset.id = n.id;
    row.title = nodeTooltip(n);
    // Per-service mini-dots so the user can see exactly which sub-service
    // is unhappy without opening the tooltip.
    const svcChips = Object.entries(n.services || {}).map(([kind, svc]) => {
      const subSev = (svc && svc.severity) || "unknown";
      return `<span class="svc"><span class="dot status-${subSev}"></span>${kind}</span>`;
    }).join("");
    row.innerHTML = `
      <span class="dot status-${sev}" aria-label="overall: ${sev}"></span>
      <input type="radio" name="node" value="${n.id}"${n.id === selectedNodeId ? " checked" : ""}>
      <span class="name">${n.name}</span>
      <code class="host">${n.host}</code>
      <span class="svcs">${svcChips}</span>
    `;
    list.appendChild(row);
  }

  list.querySelectorAll(".node-row").forEach((row) => {
    row.addEventListener("click", () => {
      selectedNodeId = row.dataset.id;
      saveEndpoint();
      list.querySelectorAll(".node-row").forEach((r) => {
        r.classList.toggle("active", r.dataset.id === selectedNodeId);
        const rb = r.querySelector('input[type="radio"]');
        if (rb) rb.checked = (r.dataset.id === selectedNodeId);
      });
    });
  });
}

function init() {
  const saved = loadEndpoint();
  selectedMiddlewareId = saved.middleware_id || null;
  selectedNodeId       = saved.node_id_selection || null;
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

  // Header toggles for Nodes / Middleware / Message. Click to expand or
  // collapse the corresponding drawer; each toggle's coloured dot reflects
  // worst-of severity (Nodes/Middleware) or last-run status (Message),
  // and stays accurate even while the drawer is closed.
  $("#nodes-toggle").addEventListener("click", toggleDrawer("nodes-toggle", "nodes-panel"));
  $("#middleware-toggle").addEventListener("click", toggleDrawer("middleware-toggle", "middleware-panel"));
  $("#message-toggle").addEventListener("click", toggleDrawer("message-toggle", "message-panel"));

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

  loadMiddlewares();
  loadNodes();
  loadTemplates();
  loadRecentRuns();

  if (nodesRefreshTimer) clearInterval(nodesRefreshTimer);
  nodesRefreshTimer = setInterval(loadNodes, NODES_REFRESH_MS);

  // Periodic middleware refresh — keeps status pills coloured in
  // without the user having to refresh the page. msf-middlewares
  // probes on its own cadence; this just pulls the latest results.
  if (mwRefreshTimer) clearInterval(mwRefreshTimer);
  mwRefreshTimer = setInterval(loadMiddlewares, MW_REFRESH_MS);
}

document.addEventListener("DOMContentLoaded", init);
