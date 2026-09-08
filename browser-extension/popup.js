"use strict";

const baseUrlEl = document.getElementById("baseUrl");
const dot = document.getElementById("dot");
const statusEl = document.getElementById("statusText");
const out = document.getElementById("out");

async function check() {
  try {
    const res = await fetch(baseUrlEl.value + "/api/health");
    const j = await res.json();
    dot.className = "dot ok";
    statusEl.textContent = "العقل: " + (j.brain || j.provider_name) + " · " + j.tools + " أدوات";
  } catch (e) {
    dot.className = "dot bad";
    statusEl.textContent = "غير متصل — الوكيل المحلي غير شغّال";
  }
}

document.getElementById("send").addEventListener("click", async () => {
  const promptText = document.getElementById("prompt").value.trim();
  if (!promptText) return;
  // Send the plain instruction; the local agent's chat/plan handles it.
  out.textContent = "…";
  try {
    const res = await fetch(baseUrlEl.value + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: promptText }),
    });
    const j = await res.json();
    out.textContent = "task_id: " + (j.task_id || "?") + "\nافتح التطبيق لمتابعة التنفيذ.";
  } catch (e) {
    out.textContent = "خطأ: " + e;
  }
});

check();
setInterval(check, 5000);
