"use strict";

// Runs on https://arena.ai.  Reads the browser page (DOM) so the local agent's
// browser-aware logic can use real DOM state, and can forward simple commands to
// the local bridge if the user opts in.  It never steals cookies/passwords.

function readPageText() {
  const body = document.body ? document.body.innerText : "";
  return body.slice(0, 8000);
}

function clickedElementInfo() {
  // Not used to leak data; only to help the agent locate elements without XY.
  const active = document.activeElement;
  if (active) {
    return {
      tag: active.tagName,
      id: active.id,
      class: (active.className || "").toString().slice(0, 80),
    };
  }
  return {};
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "ARENA_READ_PAGE") {
    sendResponse({ text: readPageText(), active: clickedElementInfo(), url: location.href });
  }
  return true;
});
