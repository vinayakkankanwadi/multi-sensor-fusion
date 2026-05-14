"use strict";

const $ = (sel) => document.querySelector(sel);

// v4 = removed UI TAK fan-out + defaults Host:Port to Apex (127.0.0.1:5020).
//      Bumping the key drops stale endpoints saved from earlier versions
//      (e.g. 127.0.0.1:14000 from the retired sapient stub).
const STORE_KEY = "msf_endpoint_v4";

function loadEndpoint() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; }
  catch { return {}; }
}
function saveEndpoint() {
  const data = {
    host: $("#host").value.trim(),
    port: Number($("#port").value),
    node_id: $("#node-id").value.trim(),
    recv_timeout_s: Number($("#recv-timeout").value),
    drain_after_s: Number($("#drain-after").value),
    validate_before_send: $("#validate-before").checked,
    auto_new_uuid: $("#auto-new-uuid").checked,
  };
  localStorage.setItem(STORE_KEY, JSON.stringify(data));
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
  if (templates.length && !currentTemplate) {
    selectTemplate(templates[0].name);
  } else if (currentTemplate && templates.find((t) => t.name === currentTemplate)) {
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
  saveEndpoint();
  $("#flow-status").textContent = "running flow...";
  $("#run-flow").disabled = true;
  try {
    const body = {
      host: $("#host").value.trim(),
      port: Number($("#port").value),
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
  const hostEl = $("#host");
  const hostOk = hostEl.value.trim().length > 0;
  hostEl.classList.toggle("missing", !hostOk);
  // Send needs both a template AND a non-empty host. Validate-only only needs a template.
  $("#send").disabled = !(currentTemplate && hostOk);
  $("#send").title = hostOk
    ? "Send the templated SapientMessage to host:port"
    : "Set a Host in the top bar before sending";
  $("#endpoint-status").textContent = hostOk
    ? ""
    : "host required before sending";
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
  return {
    host: $("#host").value.trim(),
    port: Number($("#port").value),
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

function fmtDelta(d) {
  if (d == null) return "—";
  const sign = d >= 0 ? "+" : "";
  return `${sign}${d.toFixed(3)}s`;
}

function severityBadgeClass(sev) {
  return ({ ok: "ok", warn: "warn", fail: "fail", unknown: "muted" }[sev] || "muted");
}

async function refreshClocks() {
  const badge = $("#clock-badge");
  badge.textContent = "clocks: …";
  badge.className = "badge muted";
  $("#clocks-status").textContent = "probing…";

  const params = new URLSearchParams();
  const includeWin = $("#probe-windows").checked;
  if (includeWin) {
    params.set("include_windows", "true");
    if ($("#host").value.trim()) params.set("windows_host", $("#host").value.trim());
    if ($("#port").value)         params.set("windows_port", String(Number($("#port").value)));
    // Use a DEDICATED probe UUID, not the user's Node UUID — otherwise the
    // harness sees "Another ASM is using this ID" when subsequent sends use
    // the same UUID. Stable so the probe doesn't churn registrations.
    params.set("windows_node_id", "0badc1ce-0000-4000-8000-00000000c10c");
  }

  try {
    const r = await fetch("/api/clocks?" + params.toString());
    if (!r.ok) { badge.textContent = `clocks: HTTP ${r.status}`; badge.className = "badge err"; return; }
    const data = await r.json();
    renderClocksTable(data);
    // Header badge: worst severity wins.
    const sevs = [data.deltas.local_severity, data.deltas.windows_severity];
    const worst = sevs.includes("fail") ? "fail"
                : sevs.includes("warn") ? "warn"
                : sevs.includes("ok")   ? "ok" : "muted";
    badge.className = `badge ${severityBadgeClass(worst)}`;
    const ntpDelta = data.deltas.local_minus_ref_s;
    badge.textContent = `clocks: ${data.ntp.ok ? "ntp " : "no-ntp "}${fmtDelta(ntpDelta)} ${worst}`;
    badge.title = `reference: ${data.deltas.reference_label}`;
    $("#clocks-status").textContent = "";
  } catch (exc) {
    badge.textContent = `clocks: ${exc}`;
    badge.className = "badge err";
    $("#clocks-status").textContent = String(exc);
  }
}

function renderClocksTable(data) {
  const tbody = $("#clocks-table tbody");
  tbody.innerHTML = "";

  const rows = [
    {
      label: data.ntp.label,
      time:  data.ntp.ok ? data.ntp.remote_time_iso : `(error: ${data.ntp.error || "?"})`,
      detail: data.ntp.ok ? `rtt=${(data.ntp.rtt_s || 0).toFixed(3)}s` : "",
      delta: 0,
      status: data.ntp.ok ? "reference" : "fail",
      isRef: true,
    },
    {
      label: data.local.label,
      time:  data.local.remote_time_iso,
      detail: "",
      delta: data.deltas.local_minus_ref_s,
      status: data.deltas.local_severity,
    },
  ];
  if (data.windows) {
    rows.push({
      label: data.windows.label,
      time:  data.windows.ok ? data.windows.remote_time_iso : `(error: ${data.windows.error || "?"})`,
      detail: data.windows.ok ? `rtt=${(data.windows.rtt_s || 0).toFixed(3)}s` : "",
      delta: data.deltas.windows_minus_ref_s,
      status: data.windows.ok ? data.deltas.windows_severity : "fail",
    });
  }
  if (data.gps) {
    const g = data.gps;
    let timeCell, detailCell, statusCell;
    if (g.ok) {
      timeCell   = g.timestamp || "—";
      detailCell = `lat=${g.latitude?.toFixed(7)} lon=${g.longitude?.toFixed(7)} alt=${g.altitude ?? "—"}m sats=${g.satellites ?? "—"}`;
      statusCell = "ok";
    } else {
      timeCell   = "(no fix)";
      detailCell = `error: ${g.error || "?"}`;
      statusCell = "fail";
    }
    rows.push({
      label: `GPS (${g.source})`,
      time:  timeCell,
      detail: detailCell,
      delta: null,
      status: statusCell,
      noDelta: true,
    });
  }

  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.className = severityBadgeClass(row.status);
    tr.innerHTML = `
      <td>${row.label}</td>
      <td>${row.time || "—"}</td>
      <td>${row.noDelta ? "—" : (row.isRef ? "(reference)" : fmtDelta(row.delta))}</td>
      <td>${row.status}</td>
      <td class="detail">${row.detail || ""}</td>
    `;
    tbody.appendChild(tr);
  }
  $("#clocks-panel").hidden = false;
}

function init() {
  const saved = loadEndpoint();
  // Default target is Apex on localhost (5020). Apex fans out to BSI and to
  // cot-bridge → TAK, so the UI just needs to talk to Apex.
  $("#host").value = saved.host || "127.0.0.1";
  $("#port").value = saved.port || 5020;
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
  $("#clock-badge").addEventListener("click", refreshClocks);
  $("#probe-clocks").addEventListener("click", refreshClocks);
  $("#probe-windows").addEventListener("change", refreshClocks);
  $("#refresh-runs")?.addEventListener("click", loadRecentRuns);

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
  ["host","port","node-id","recv-timeout","drain-after"].forEach((id) => {
    $("#" + id).addEventListener("change", saveEndpoint);
  });
  $("#validate-before").addEventListener("change", saveEndpoint);
  $("#auto-new-uuid").addEventListener("change", saveEndpoint);
  // Live-update Send button as Host is typed.
  $("#host").addEventListener("input", refreshSendButton);
  refreshSendButton();

  loadTemplates();
  loadRecentRuns();
  refreshClocks();
}

document.addEventListener("DOMContentLoaded", init);
