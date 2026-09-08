"use strict";

/* ------------------------------------------------------------------ state */
let currentTaskId = null;
let eventSource = null;
let kindToState = {
  task_created: "pending", planning: "planning", plan_ready: "planning",
  step_started: "executing", tool_call: "executing", tool_result: "executing",
  verifying: "verifying", verified: "verified", waiting_approval: "waiting",
  approval_resolved: "executing", recovered: "executing", recovering: "recovering",
  completed: "completed", failed: "failed", cancelled: "cancelled",
};
let kindToIcon = {
  plan_ready: "🧭", planning: "🧭", step_started: "▶️", tool_call: "🔧",
  tool_result: "📦", verifying: "✅", verified: "✅", waiting_approval: "⚠️",
  approval_resolved: "👍", recovered: "🛠️", recovering: "🛠️",
  completed: "🏁", failed: "❌", cancelled: "✖️", task_created: "🎯", log: "•",
};

/* ------------------------------------------------------------------ utils */
async function json(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(res.status + " " + (await res.text()));
  return res.json();
}
function el(id) { return document.getElementById(id); }
function escapeHtml(s) { return (s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

/* ------------------------------------------------------------------ boot */
async function boot() {
  try {
    const h = await json("/api/health");
    el("provider").textContent = h.provider_name;
    el("toolCount").textContent = h.tools;
  } catch (e) { el("provider").textContent = "offline"; }
  setConn(true);
  await refreshTasks();
  await refreshTools();
  await refreshWorkflows();
  bindNav();
}

function setConn(online) {
  el("connDot").className = "dot " + (online ? "ok" : "err");
  el("conn").textContent = online ? "live" : "offline";
}

/* ------------------------------------------------------------------ nav */
function bindNav() {
  document.querySelectorAll(".nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      document.getElementById("panel-" + tab).classList.add("active");
    });
  });
  bindTaskActions();
}

/* ------------------------------------------------------------------ tasks */
async function refreshTasks() {
  const tasks = await json("/api/tasks");
  const list = el("taskList");
  if (!tasks.length) { list.innerHTML = '<div class="task-list-empty">No tasks yet. Create one above.</div>'; return; }
  list.innerHTML = tasks.map(t => `
    <div class="task-item ${t.id === currentTaskId ? "sel" : ""}" data-id="${t.id}">
      <div class="ti-goal">${escapeHtml(t.goal)}</div>
      <div class="ti-meta"><span >${(t.state || "").toUpperCase()}</span><span>${new Date(t.created_at).toLocaleTimeString()}</span></div>
    </div>`).join("");
  list.querySelectorAll(".task-item").forEach(item => {
    item.addEventListener("click", () => selectTask(item.dataset.id));
  });
}

async function selectTask(id) {
  currentTaskId = id;
  el("taskList").querySelectorAll(".task-item").forEach(i => i.classList.toggle("sel", i.dataset.id === id));
  const d = await json("/api/tasks/" + id);
  renderTaskPanel(d);
  openSSE(id);
}

function renderTaskPanel(d) {
  el("taskPanelEmpty").classList.add("hidden");
  el("taskPanelBody").classList.remove("hidden");
  el("taskTitle").textContent = d.goal;
  const badge = el("taskState");
  badge.textContent = (d.state || "").toUpperCase();
  badge.className = "badge " + (d.state || "");
  const steps = d.plan ? d.plan.steps : [];
  const done = steps.filter(s => s.status === "ok").length;
  const total = steps.length;
  el("progressText").textContent = `${done}/${total} steps`;
  el("progressFill").style.width = total ? (done / total * 100) + "%" : "0%";
}

/* ------------------------------------------------------------------ SSE */
function openSSE(taskId) {
  if (eventSource) { eventSource.close(); }
  const es = new EventSource("/api/tasks/" + taskId + "/events");
  eventSource = es;
  es.onopen = () => setConn(true);
  es.onerror = () => setConn(false);
  es.onmessage = (msg) => {
    try { const evt = JSON.parse(msg.data); renderEvent(evt); } catch (e) {}
  };
}

function renderEvent(evt) {
  // Timeline
  const empty = el("timelineEmpty");
  if (empty) empty.remove();
  const timeline = el("timeline");
  const item = document.createElement("div");
  item.className = "tl-item " + (evt.kind === "completed" ? "ok" : evt.kind === "failed" || evt.kind === "cancelled" ? "err" : evt.kind.startsWith("wait") ? "warn" : "info");
  let detail = "";
  const payload = evt.payload || {};
  if (payload.tool) detail = "tool: " + payload.tool;
  if (evt.kind === "tool_result" && payload.observation) {
    detail = escapeHtml(payload.observation.summary || "");
  }
  item.innerHTML = `
    <div class="tl-icon">${kindToIcon[evt.kind] || "•"}</div>
    <div class="tl-body">
      <div class="tl-title">${escapeHtml(evt.message || evt.kind)}</div>
      ${detail ? `<div class="tl-detail">${detail}</div>` : ""}
      <div class="tl-meta">${new Date(evt.ts).toLocaleTimeString()}</div>
    </div>`;
  timeline.appendChild(item);
  timeline.scrollTop = timeline.scrollHeight;

  // Terminal output for tool_result / shell
  if (evt.kind === "tool_result" && payload.observation && payload.observation.output) {
    const tb = el("terminalBody");
    const line = document.createElement("div");
    line.className = "term-line " + (payload.observation.ok ? "ok" : "err");
    line.textContent = `$ ${payload.tool}\n` + payload.observation.output;
    tb.appendChild(line);
    tb.scrollTop = tb.scrollHeight;
  }

  // Approval
  if (evt.kind === "waiting_approval") {
    el("approvalBox").classList.remove("hidden");
    el("approvalMsg").textContent = "⚠ " + evt.message;
  } else if (evt.kind === "approval_resolved") {
    el("approvalBox").classList.add("hidden");
  }

  // Update badge/progress by re-fetching (cheap) state
  const st = kindToState[evt.kind];
  if (st) { el("taskState").textContent = st.toUpperCase(); el("taskState").className = "badge " + st; }

  if (evt.kind === "completed" || evt.kind === "failed" || evt.kind === "cancelled") {
    refreshTasks();
  }
}

/* ------------------------------------------------------------------ actions */
function bindTaskActions() {
  el("submitGoal").addEventListener("click", submitGoal);
  el("goalInput").addEventListener("keydown", e => { if (e.key === "Enter") submitGoal(); });
  el("btnCancel").addEventListener("click", async () => {
    if (!currentTaskId) return;
    await json("/api/tasks/" + currentTaskId + "/cancel", { method: "POST" });
  });
  el("btnApprove").addEventListener("click", () => decide(true));
  el("btnDeny").addEventListener("click", () => decide(false));
}

async function submitGoal() {
  const goal = el("goalInput").value.trim();
  if (!goal) return;
  el("goalInput").value = "";
  try {
    const task = await json("/api/tasks", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goal }),
    });
    await refreshTasks();
    await selectTask(task.id);
  } catch (e) { alert("Failed to create task: " + e.message); }
}

async function decide(approved) {
  if (!currentTaskId) return;
  await json("/api/tasks/" + currentTaskId + "/approve", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved }),
  });
}

/* ------------------------------------------------------------------ tools */
async function refreshTools() {
  const data = await json("/api/tools");
  const grid = el("toolGrid");
  grid.innerHTML = data.summary.tools.map(t => `
    <div class="tool-card">
      <div class="tc-head"><span class="tc-name">${escapeHtml(t.name)}</span><span class="tc-cat">${escapeHtml(t.category)}</span></div>
      <div class="tc-perm ${escapeHtml(t.permission)}">${escapeHtml(t.permission)}</div>
      <div class="tc-desc">${escapeHtml(t.description)}</div>
      <div class="tc-params">${escapeHtml(JSON.stringify(t.parameters))}</div>
    </div>`).join("");
}

/* ------------------------------------------------------------------ workflows */
async function refreshWorkflows() {
  const wfs = await json("/api/workflows");
  const grid = el("wfGrid");
  grid.innerHTML = wfs.map(w => `
    <div class="wf-card">
      <h3>${escapeHtml(w.name)}</h3>
      <p>${escapeHtml(w.description)}</p>
      <div class="wf-nodes">${w.nodes.map(n => (n.type === "tool" ? "⚙️" : n.type === "trigger" ? "🔔" : "🔀") + " " + n.id).join(" → ")}</div>
    </div>`).join("");
}

/* ------------------------------------------------------------------ misc */
el("refreshTasks").addEventListener("click", refreshTasks);
el("refreshTools").addEventListener("click", refreshTools);
el("refreshWorkflows").addEventListener("click", refreshWorkflows);

boot();
