"""Web / Internet tools.

The agent needs to browse and fetch the web.  These tools are optional —
``playwright`` (for real browser control) is imported lazily and is guarded so
the platform still runs without it.  ``fetch_page`` and ``web_search`` use only
the stdlib (urllib) so they always work.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

from agent_platform.models.schemas import PermissionLevel, ToolResult, ToolSpec
from agent_platform.tools.base import Tool

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


class FetchPageTool(Tool):
    spec = ToolSpec(
        name="fetch_page",
        description="Fetch the text content of a web page / URL and return it as "
        "markdown-ish text. Uses simple HTML-to-text. Use for reading pages "
        "and API endpoints.",
        category="web",
        parameters={"url": "str (required)", "max_chars": "int (optional, default 20000)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, url: str, max_chars: int = 20000, **kwargs: Any) -> ToolResult:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            if "html" in (resp.headers.get("content-type", "") or "").lower():
                text = _html_to_text(raw)
            else:
                text = raw
            return self.ok(text[:max_chars], data={"url": url})
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc), output=url)


class WebSearchTool(Tool):
    spec = ToolSpec(
        name="web_search",
        description="Search the web (DuckDuckGo HTML) for a query and return a "
        "list of top result titles and links.",
        category="web",
        parameters={"query": "str (required)", "max_results": "int (optional, default 8)"},
        permission=PermissionLevel.SAFE,
    )

    def run(self, query: str, max_results: int = 8, **kwargs: Any) -> ToolResult:
        try:
            url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            results = _parse_ddg_results(html, max_results)
            if not results:
                return self.ok(f"No results for '{query}'")
            return self.ok(json.dumps(results, ensure_ascii=False, indent=2), data=results)
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc), output=query)


class OpenBrowserTool(Tool):
    """Real browser control via Playwright (optional dependency)."""

    spec = ToolSpec(
        name="browser_control",
        description="Control a real browser via Playwright. Actions: navigate, "
        "click, type, extract, screenshot. Requires the 'playwright' package.",
        category="web",
        parameters={"action": "str (required): navigate|click|type|extract|screenshot",
                     "url": "str (optional)", "selector": "str (optional)",
                     "text": "str (optional)", "value": "str (optional)"},
        permission=PermissionLevel.SENSITIVE,
    )

    def run(self, action: str = "navigate", url: str = "", selector: str = "",
            text: str = "", value: str = "", **kwargs: Any) -> ToolResult:
        try:
            import playwright  # noqa: F401
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError:
            return self.fail(
                "Playwright is not installed. Run: pip install playwright && "
                "playwright install chromium"
            )
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                if action == "navigate":
                    page.goto(url)
                    return self.ok(f"Navigated to {url} | title={page.title()}")
                if action == "extract":
                    text_content = page.inner_text("body") if selector else page.content()
                    return self.ok(text_content[:20000])
                if action == "screenshot":
                    page.screenshot(path=value or "browser.png")
                    return self.ok(f"Screenshot saved to {value or 'browser.png'}")
                browser.close()
                return self.fail(f"Unsupported action '{action}'")
        except Exception as exc:  # noqa: BLE001
            return self.fail(str(exc))


def _html_to_text(html: str) -> str:
    # Remove script/style.
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    # Replace block tags with newlines.
    html = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|br|section|article)>", "\n", html)
    html = re.sub(r"(?i)<(p|div|li|h[1-6]|tr|section|article|br)[^>]*>", "\n", html)
    # Strip remaining tags.
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#39;|&quot;", "'", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_ddg_results(html: str, max_results: int) -> list[dict[str, str]]:
    results = []
    # Classic DDG HTML results are <a class="result__a" href="...">title</a>
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html):
        link = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2))
        title = re.sub(r"\s+", " ", title).strip()
        results.append({"title": title, "url": link})
        if len(results) >= max_results:
            break
    return results


ALL_TOOLS: list[type[Tool]] = [FetchPageTool, WebSearchTool, OpenBrowserTool]
