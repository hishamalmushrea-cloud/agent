"use strict";

// Service worker: relays messages between the Arena page (content.js) and the
// local agent bridge (http://127.0.0.1:8000).  Used when a content script needs
// to pass a command from an Arena conversation to the local agent.

async function sendToLocalAgent(payload, baseUrl) {
  try {
    const res = await fetch(baseUrl + "/api/actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch (e) { data = { raw: text }; }
    return { ok: res.ok, data };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "ARENA_ACTION") {
    const baseUrl = msg.baseUrl || "http://127.0.0.1:8000";
    sendToLocalAgent(msg.action, baseUrl).then(sendResponse);
    return true; // async
  }
});
