"use strict";

/* ------------------------------------------------------------- state */
let currentConv = null;      // current conversation/task id
let eventSource = null;
let threadOpen = false;      // has a thread been started
let statusTimer = null;
let desktopTimer = null;
const kindIcon = {
  planning: "🧭", plan_ready: "🧭", step_started: "▶️", tool_call: "🔧",
  tool_result: "📦", verifying: "✅", verified: "✅", waiting_approval: "⚠️",
  approval_resolved: "👍", recovered: "🛠️", recovering: "🛠️",
  completed: "🏁", failed: "❌", cancelled: "✖️", assistant: "💬", log: "•",
};
const kindToStatus = {
  step_started: "running", tool_call: "running", tool_result: "running",
  verified: "ok", recovered: "ok", recovering: "recovering",
};

/* ------------------------------------------------------------- helpers */
async function json(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(res.status + " " + (await res.text()));
  return res.json();
}
function el(id) { return document.getElementById(id); }
function escapeHtml(s) { return (s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function scrollChat() { const c = el("chat"); c.scrollTop = c.scrollHeight; }

/* ------------------------------------------------------------- boot */
async function boot() {
  try {
    const h = await json("/api/health");
    el("brainLabel").textContent = h.brain || h.provider_name;
    el("toolCount").textContent = h.tools;
    el("brainMeta").textContent = h.brain || "";
    el("brainMeta2").textContent = h.brain || "";
    setConn(true);
  } catch (e) { setConn(false); }
  await refreshConvs();
  await refreshStatus();
  bindUI();
  startStatusPolling();
  startDesktopPolling();
  maybeShowWizard();
}
function setConn(online) {
  el("connDot") && (el("connDot").className = "dot " + (online ? "ok" : "err"));
  el("conn").textContent = online ? "live" : "offline";
}

function maybeShowWizard() {
  // Show the first-run wizard only once (per browser).
  if (!localStorage.getItem("aw_wizard_seen")) {
    el("wizardModal").classList.remove("hidden");
  }
}

/* ------------------------------------------------------------- status */
async function refreshStatus() {
  try {
    const r = await json("/api/runtime");
    const st = (r.status || "IDLE").toUpperCase();
    el("agentStatus").textContent = st;
    const dot = el("statusDot");
    dot.className = "pulse";
    if (st === "STOPPED") dot.className = "pulse stopped";
    else if (st === "EXECUTING") dot.className = "pulse running";
    else if (st === "WAITING_FOR_USER") dot.className = "pulse warn";
    else if (st === "IDLE" || st === "COMPLETED") dot.className = "pulse ok";
  } catch (e) { /* ignore */ }
  try {
    const tasks = await json("/api/tasks");
    const running = tasks.filter(t => ["planning","executing","waiting","verifying","recovering"].includes(t.state)).length;
    el("runningTasks").textContent = running;
  } catch (e) { /* ignore */ }
}

function startStatusPolling() {
  if (statusTimer) return;
  statusTimer = setInterval(refreshStatus, 3000);
}

/* ------------------------------------------------------------- desktop */
async function refreshDesktop() {
  const view = el("desktopView");
  const note = el("desktopNote");
  try {
    const res = await fetch("/api/desktop");
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("image")) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      view.innerHTML = `<img src="${url}" alt="live desktop" />`;
      note.textContent = "آخر لقطة " + new Date().toLocaleTimeString();
      return;
    }
    const j = await res.json();
    view.innerHTML = `<div class="desktop-placeholder">${escapeHtml(j.error || "غير متاح")}</div>`;
    note.textContent = "";
  } catch (e) {
    view.innerHTML = `<div class="desktop-placeholder">غير متاح</div>`;
    note.textContent = "";
  }
}
function startDesktopPolling() {
  if (desktopTimer) return;
  desktopTimer = setInterval(refreshDesktop, 7000);
}

/* ------------------------------------------------------------- conversations */
async function refreshConvs() {
  const tasks = await json("/api/tasks");
  const list = el("convList");
  if (!tasks.length) {
    list.innerHTML = '<div class="conv-empty">لا توجد محادثات بعد.</div>';
  } else {
    list.innerHTML = tasks.slice(0, 30).map(t => `
      <div class="conv-item ${t.id === currentConv ? "sel" : ""}" data-id="${t.id}">
        <div class="ci-goal">${escapeHtml(t.goal)}</div>
        <div class="ci-meta">${escapeHtml((t.state || "").toUpperCase())} · ${new Date(t.created_at).toLocaleTimeString()}</div>
      </div>`).join("");
    list.querySelectorAll(".conv-item").forEach(it =>
      it.addEventListener("click", () => openConv(it.dataset.id)));
  }
}

function newConversation() {
  currentConv = null;
  threadOpen = false;
  el("chatEmpty").classList.remove("hidden");
  el("chatThread").classList.add("hidden");
  el("chatThread").innerHTML = "";
  el("timelineWrap") && (el("timelineWrap").style.display = "none");
  el("timeline").innerHTML = "";
  if (eventSource) { eventSource.close(); eventSource = null; }
  el("input").focus();
}

async function openConv(id) {
  currentConv = id;
  refreshConvs();
  const detail = await json("/api/tasks/" + id);
  showChat();
  const thread = el("chatThread");
  thread.innerHTML = "";
  if (detail.messages) {
    for (const m of detail.messages) {
      if (m.role === "user") addUserMsg(m.content);
      else if (m.role === "assistant") addAssistantMsg(m.content);
    }
  }
  // Render plan steps as collapsible activity + timeline.
  if (detail.plan && detail.plan.steps) {
    el("timelineWrap").style.display = "";
    for (const s of detail.plan.steps) {
      addStep(s, {});
      addTimeline(s);
    }
  }
  if (detail.state === "waiting") addApproval(detail, {});
  openSSE(id);
}

function showChat() {
  el("chatEmpty").classList.add("hidden");
  el("chatThread").classList.remove("hidden");
  threadOpen = true;
}

/* ------------------------------------------------------------- send */
async function sendMessage() {
  const input = el("input");
  const text = input.value.trim();
  if (!text) return;
  input.value = ""; autoSize();
  addUserMsg(text);
  showChat();
  setTimeout(refreshConvs, 400);
  try {
    const res = await json("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, conversation_id: currentConv || "" }),
    });
    if (!currentConv) { currentConv = res.task_id; }
    el("timelineWrap").style.display = "";
    openSSE(res.task_id);
  } catch (e) {
    addAssistantMsg("⚠️ تعذّر بدء المهمة: " + e.message);
  }
}

/* ------------------------------------------------------------- SSE */
function openSSE(taskId) {
  if (eventSource) eventSource.close();
  const es = new EventSource("/api/tasks/" + taskId + "/events");
  eventSource = es;
  es.onopen = () => setConn(true);
  es.onerror = () => setConn(false);
  es.onmessage = (msg) => {
    try { renderEvent(JSON.parse(msg.data)); } catch (e) {}
  };
}

function renderEvent(evt) {
  if (!threadOpen) showChat();
  const thread = el("chatThread");

  if (evt.kind === "assistant") {
    addAssistantMsg(evt.message);
  } else if (evt.kind === "step_started") {
    const s = (evt.payload || {}).step || {};
    addStep(s, evt.payload);
    addTimeline({ ...s, _status: "running" });
  } else if (evt.kind === "tool_call") {
    updateStepStatus(evt.payload.tool, "running");
  } else if (evt.kind === "tool_result") {
    updateStepWithResult(evt.payload);
    updateTimelineStatus(evt.payload.tool);
  } else if (evt.kind === "verified") {
    markLastOk();
    markTimelineOk(evt.payload.step || evt.payload);
  } else if (evt.kind === "waiting_approval") {
    addApproval(evt.payload, evt);
  } else if (evt.kind === "approval_resolved") {
    removeApproval();
  } else if (evt.kind === "completed" || evt.kind === "failed") {
    addRunResult(evt.kind, evt.message);
    refreshConvs();
    refreshStatus();
  } else if (evt.kind === "recovering") {
    addNote("🛠️ " + evt.message, "warn");
  }
  scrollChat();
}

/* ------------------------------------------------------------- rendering */
function addUserMsg(text) {
  const t = el("chatThread");
  const d = document.createElement("div");
  d.className = "msg user";
  d.innerHTML = `<div class="avatar">👤</div><div class="bubble"><div class="who">أنت</div><div class="text">${escapeHtml(text)}</div></div>`;
  t.appendChild(d);
}
function addAssistantMsg(text) {
  const t = el("chatThread");
  const d = document.createElement("div");
  d.className = "msg assistant";
  d.innerHTML = `<div class="avatar">🤖</div><div class="bubble"><div class="who">الوكيل</div><div class="text">${escapeHtml(text)}</div></div>`;
  t.appendChild(d);
}
function addStep(spec, payload) {
  const t = el("chatThread");
  const id = "step_" + (spec.id || Math.random().toString(36).slice(2));
  const s = document.createElement("div");
  s.className = "step";
  s.id = id;
  const tool = spec.tool ? `<span class="tool-name">${escapeHtml(spec.tool)}</span>` : "";
  s.innerHTML = `
    <div class="step-head">
      <span class="step-chev">▶</span>
      <span class="step-icon">${tool ? "🔧" : "🧩"}</span>
      <span class="step-title">${escapeHtml(spec.title || spec.description || "خطوة")}</span>
      <span class="step-status running">⏳</span>
    </div>
    <div class="step-body">
      <div class="step-out">${escapeHtml(spec.verification || "")}</div>
      <pre></pre>
    </div>`;
  s.querySelector(".step-head").addEventListener("click", () => s.classList.toggle("open"));
  t.appendChild(s);
  return s;
}
function updateStepStatus(tool, status) {
  const steps = el("chatThread").querySelectorAll(".step");
  for (let i = steps.length - 1; i >= 0; i--) {
    const toolName = steps[i].querySelector(".tool-name");
    if (toolName && toolName.textContent === tool) {
      const st = steps[i].querySelector(".step-status");
      st.textContent = kindToStatus[status] || status;
      st.className = "step-status " + (kindToStatus[status] || status);
      return;
    }
  }
}
function updateStepWithResult(payload) {
  const obs = payload.observation || {};
  const tool = payload.tool || obs.tool;
  const steps = el("chatThread").querySelectorAll(".step");
  for (let i = steps.length - 1; i >= 0; i--) {
    const toolName = steps[i].querySelector(".tool-name");
    if (toolName && toolName.textContent === tool) {
      const pre = steps[i].querySelector("pre");
      if (pre && obs.output) pre.textContent = (obs.output || "").slice(0, 2000);
      const st = steps[i].querySelector(".step-status");
      st.textContent = obs.ok ? "✓ ok" : "✗ failed";
      st.className = "step-status " + (obs.ok ? "ok" : "failed");
      return;
    }
  }
}
function markLastOk() {
  const steps = el("chatThread").querySelectorAll(".step-status.running, .step-status.recovering");
  const last = steps[steps.length - 1];
  if (last) { last.textContent = "✓ ok"; last.className = "step-status ok"; }
}
function addNote(text, cls) {
  const t = el("chatThread");
  const d = document.createElement("div");
  d.className = "run-result " + (cls || "");
  d.textContent = text;
  t.appendChild(d);
}
function addRunResult(kind, msg) {
  const t = el("chatThread");
  const d = document.createElement("div");
  d.className = "run-result " + (kind === "completed" ? "done" : "failed");
  d.textContent = kind === "completed" ? ("✅ " + msg) : ("❌ " + msg);
  t.appendChild(d);
}
function addApproval(payload, evt) {
  const t = el("chatThread");
  const tool = payload.tool || "أداة";
  const d = document.createElement("div");
  d.className = "approval-inline";
  d.id = "approvalBox";
  d.innerHTML = `
    <div>⚠️ يتطلب موافقتك: <b>${escapeHtml(tool)}</b></div>
    <div class="btns"><button class="btn wan" data-a="1">موافقة</button>
    <button class="btn danger" data-a="0">رفض</button></div>`;
  d.querySelectorAll("button").forEach(b => b.addEventListener("click", async () => {
    const approved = b.dataset.a === "1";
    await json("/api/tasks/" + currentConv + "/approve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
  }));
  t.appendChild(d);
}
function removeApproval() { const b = el("approvalBox"); if (b) b.remove(); }

/* ------------------------------------------------------------- timeline */
function addTimeline(step) {
  const tl = el("timeline");
  const id = "tl_" + (step.id || "s" + Math.random().toString(36).slice(2));
  const d = document.createElement("div");
  d.className = "tl-item";
  d.id = id;
  const tool = step.tool ? `<span class="tl-tool">${escapeHtml(step.tool)}</span>` : "";
  d.innerHTML = `
    <div class="tl-line">${escapeHtml(step.title || step.description || "خطوة")} ${tool}</div>
    <div class="tl-status">${escapeHtml(step._status || step.status || "pending")}</div>`;
  tl.appendChild(d);
  return id;
}
function updateTimelineStatus(tool) {
  const items = el("timeline").querySelectorAll(".tl-item");
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].querySelector(".tl-tool") && items[i].querySelector(".tl-tool").textContent === tool) {
      items[i].classList.add("running");
      items[i].querySelector(".tl-status").textContent = "running";
      return;
    }
  }
}
function markTimelineOk(stepRef) {
  const items = el("timeline").querySelectorAll(".tl-item.running");
  const last = items[items.length - 1];
  if (last) { last.classList.add("done"); last.classList.remove("running"); last.querySelector(".tl-status").textContent = "ok"; }
}
function markTimelineFailed(stepRef) {
  const items = el("timeline").querySelectorAll(".tl-item.running");
  const last = items[items.length - 1];
  if (last) { last.classList.add("failed"); last.classList.remove("running"); last.querySelector(".tl-status").textContent = "failed"; }
}

/* ------------------------------------------------------------- settings / connect brain */
async function openSettings() {
  try {
    const s = await json("/api/settings");
    el("setArenaUrl").value = s.arena_endpoint || "";
    el("setArenaKey").value = s.arena_api_key || "";
    el("setLlmUrl").value = s.llm_base_url || "";
    el("setLlmKey").value = s.llm_api_key || "";
    el("setModel").value = s.model || "";
    el("setApproval").value = s.approval_mode || "safe";
  } catch (e) {}
  el("settingsModal").classList.remove("hidden");
}
async function saveSettings() {
  const body = {
    arena_endpoint: el("setArenaUrl").value.trim(),
    arena_api_key: el("setArenaKey").value.trim(),
    llm_base_url: el("setLlmUrl").value.trim(),
    llm_api_key: el("setLlmKey").value.trim(),
    model: el("setModel").value.trim(),
    approval_mode: el("setApproval").value,
  };
  try {
    const s = await json("/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    el("brainLabel").textContent = s.brain;
    el("brainMeta").textContent = s.brain;
    el("brainMeta2").textContent = s.brain;
    el("saveMsg").textContent = "تم الحفظ والربط ✓";
    el("settingsModal").classList.add("hidden");
    setModeTabs(el("setApproval").value);
  } catch (e) {
    el("saveMsg").textContent = "خطأ: " + e.message;
  }
}

/* ------------------------------------------------------------- execution mode */
function setModeTabs(mode) {
  const tab = document.querySelector(`.mode[data-mode="${mode}"]`);
  document.querySelectorAll(".mode").forEach(m => m.classList.remove("active"));
  if (tab) tab.classList.add("active");
  const hints = { safe: "safe: تأكيد الحساس/الخطير", auto: "auto: تنفيذ كل شيء", strict: "strict: تأكيد كل شيء", banned: "banned: منع الخطير" };
  el("modeHint").textContent = hints[mode] || mode;
}
async function changeMode(mode) {
  try {
    await json("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approval_mode: mode }) });
    setModeTabs(mode);
    refreshStatus();
  } catch (e) {}
}

/* ------------------------------------------------------------- emergency stop / reset */
async function emergencyStop() {
  if (!confirm("إيقاف طارئ؟ هذا سيمنع أي إجراء جديد.")) return;
  try { await json("/api/stop", { method: "POST" }); refreshStatus(); } catch (e) {}
}
async function resetAgent() {
  try { await json("/api/reset", { method: "POST" }); refreshStatus(); } catch (e) {}
}

/* ------------------------------------------------------------- permissions */
async function openPermissions() {
  try {
    const info = await json("/api/mcp/info");
    const grants = info.grants || { tools: [], auto_approve: false };
    const grid = el("permGrid");
    grid.innerHTML = info.tools.map(t => `
      <div class="perm-card">
        <div class="pc-name">${escapeHtml(t.name)}</div>
        <div class="pc-cat">${escapeHtml(t.category)} · ${escapeHtml(t.permission)}</div>
        <div class="pc-row">
          <label>${escapeHtml(t.permission === "safe" ? "آمن" : t.permission === "sensitive" ? "حساس" : "خطير")}</label>
          <input type="checkbox" class="perm-check" data-tool="${escapeHtml(t.name)}"
                 ${grants.tools.includes(t.name) ? "checked" : ""} />
        </div>
      </div>`).join("");
    el("autoGrant").checked = !!grants.auto_approve;
    el("permModal").classList.remove("hidden");
  } catch (e) { el("permMsg").textContent = "خطأ: " + e.message; }
}
async function savePermissions() {
  const checks = document.querySelectorAll(".perm-check");
  let okAll = true;
  for (const c of checks) {
    const tool = c.dataset.tool;
    const granted = c.checked;
    try {
      await json("/api/mcp/grants", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool, granted }),
      });
    } catch (e) { okAll = false; }
  }
  await json("/api/mcp/grants", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tool: "", auto_approve: el("autoGrant").checked }),
  });
  el("permMsg").textContent = okAll ? "تم حفظ الأذونات ✓" : "حدث خطأ أثناء الحفظ";
}

/* ------------------------------------------------------------- diagnostics */
async function openDiagnostics() {
  el("diagModal").classList.remove("hidden");
  try {
    const d = await json("/api/diagnostics");
    const grid = el("diagGrid");
    grid.innerHTML = (d.results || []).map(r => `
      <div class="diag-item ${r.ok ? "ok" : "bad"}">
        <div class="dc-name">${escapeHtml(r.component)}</div>
        <div class="dc-status">${r.ok ? "✓ متاح" : "✗ غير متاح"}${r.note ? " — " + escapeHtml(r.note) : ""}</div>
      </div>`).join("");
    const a = await json("/api/audit");
    const list = el("auditList");
    if (!a.entries || !a.entries.length) {
      list.innerHTML = '<div class="muted">لا يوجد نشاط.</div>';
    } else {
      list.innerHTML = a.entries.slice(-25).reverse().map(e => `
        <div class="audit-entry">
          <span class="ae-time">${escapeHtml(e.time)}</span> ·
          <span class="ae-act">${escapeHtml(e.action)}</span> —
          ${escapeHtml(e.result)}${e.error ? " · " + escapeHtml(e.error) : ""}
        </div>`).join("");
    }
  } catch (e) {
    el("diagGrid").innerHTML = '<div class="muted">خطأ: ' + escapeHtml(e.message) + "</div>";
  }
}

/* ------------------------------------------------------------- UI bind */
function bindUI() {
  el("send").addEventListener("click", sendMessage);
  el("newChat").addEventListener("click", newConversation);
  el("openSettings").addEventListener("click", openSettings);
  el("closeSettings").addEventListener("click", () => el("settingsModal").classList.add("hidden"));
  el("saveSettings").addEventListener("click", saveSettings);
  el("openPermissions").addEventListener("click", openPermissions);
  el("closePerm").addEventListener("click", () => el("permModal").classList.add("hidden"));
  el("savePerm").addEventListener("click", savePermissions);
  el("refreshPerm").addEventListener("click", openPermissions);
  el("emergencyStop").addEventListener("click", emergencyStop);
  el("resetAgent").addEventListener("click", resetAgent);
  el("openDiagnostics").addEventListener("click", openDiagnostics);
  el("closeDiag").addEventListener("click", () => el("diagModal").classList.add("hidden"));
  el("refreshDesktop").addEventListener("click", refreshDesktop);
  el("desktopView").addEventListener("click", refreshDesktop);
  // Mode tabs.
  document.querySelectorAll(".mode").forEach(m => m.addEventListener("click", () => changeMode(m.dataset.mode)));
  // Wizard.
  el("closeWizard").addEventListener("click", () => { el("wizardModal").classList.add("hidden"); localStorage.setItem("aw_wizard_seen", "1"); });
  el("wizardGo").addEventListener("click", () => { el("wizardModal").classList.add("hidden"); localStorage.setItem("aw_wizard_seen", "1"); });

  const input = el("input");
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  input.addEventListener("input", autoSize);
  document.querySelectorAll(".sug").forEach(b =>
    b.addEventListener("click", () => { el("input").value = b.dataset.g; autoSize(); sendMessage(); }));

  // Initialize the mode tabs from current settings.
  (async () => {
    try { const s = await json("/api/settings"); setModeTabs(s.approval_mode || "safe"); } catch (e) {}
  })();
}
function autoSize() {
  const t = el("input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 180) + "px";
}

boot();
