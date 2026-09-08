"use strict";

/* ------------------------------------------------------------- state */
let currentConv = null;      // current conversation/task id
let eventSource = null;
let threadOpen = false;      // has a thread been started
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
    setConn(true);
  } catch (e) { setConn(false); }
  await refreshConvs();
  bindUI();
}
function setConn(online) {
  el("connDot").className = "dot " + (online ? "ok" : "err");
  el("conn").textContent = online ? "live" : "offline";
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
  if (eventSource) { eventSource.close(); eventSource = null; }
  el("input").focus();
}

async function openConv(id) {
  currentConv = id;
  refreshConvs();
  const detail = await json("/api/tasks/" + id);
  showChat();
  // Rebuild the thread from existing messages + current plan.
  const thread = el("chatThread");
  thread.innerHTML = "";
  if (detail.messages) {
    for (const m of detail.messages) {
      if (m.role === "user") addUserMsg(m.content);
      else if (m.role === "assistant") addAssistantMsg(m.content);
    }
  }
  // Render plan steps as collapsible activity.
  if (detail.plan && detail.plan.steps) {
    for (const s of detail.plan.steps) addStep(s, {});
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
  // Refresh conversation list after a moment (to show the new conv).
  setTimeout(refreshConvs, 400);
  try {
    const res = await json("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, conversation_id: currentConv || "" }),
    });
    if (!currentConv) { currentConv = res.task_id; }
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
  } else if (evt.kind === "tool_call") {
    updateStepStatus(evt.payload.tool, "running");
  } else if (evt.kind === "tool_result") {
    updateStepWithResult(evt.payload);
  } else if (evt.kind === "verified") {
    markLastOk();
  } else if (evt.kind === "waiting_approval") {
    addApproval(evt.payload, evt);
  } else if (evt.kind === "approval_resolved") {
    removeApproval();
  } else if (evt.kind === "completed" || evt.kind === "failed") {
    addRunResult(evt.kind, evt.message);
    refreshConvs();
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
      ${tool ? "" : ""}
      <div class="step-out">${escapeHtml(spec.verification || "")}</div>
      <pre></pre>
    </div>`;
  s.querySelector(".step-head").addEventListener("click", () => s.classList.toggle("open"));
  t.appendChild(s);
  return s;
}
function updateStepStatus(tool, status) {
  // Find the step with this tool's name (last added).
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
  // Find the step whose tool matches; attach the output.
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
  // Mark the last running step as ok if still running.
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
  const args = JSON.stringify(payload.arguments || {});
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

/* ------------------------------------------------------------- UI bind */
function bindUI() {
  el("send").addEventListener("click", sendMessage);
  el("newChat").addEventListener("click", newConversation);
  const input = el("input");
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  input.addEventListener("input", autoSize);
  document.querySelectorAll(".sug").forEach(b =>
    b.addEventListener("click", () => { el("input").value = b.dataset.g; autoSize(); sendMessage(); }));
}
function autoSize() {
  const t = el("input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 180) + "px";
}

boot();
