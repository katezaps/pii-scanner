"""discover_forms tool — navigates to a URL and extracts form structure."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from agents import function_tool
from playwright.async_api import BrowserContext
from playwright.async_api import TimeoutError as PlaywrightTimeout

from src.services.browser import new_page

_DEFAULT_PAGE_TIMEOUT_MS = 30_000

_SEARCH_LINK_RE = re.compile(
    r"search|find|look.?up|people|person|name|phone|email|address", re.IGNORECASE
)


async def _extract_forms(page) -> list[dict]:
    """Extract forms from the rendered page using Playwright DOM queries."""
    forms = []
    for form_el in await page.query_selector_all("form"):
        action = await form_el.get_attribute("action") or ""
        method = (await form_el.get_attribute("method") or "GET").upper()
        fields = []
        for input_el in await form_el.query_selector_all("input, select, textarea"):
            name = await input_el.get_attribute("name") or await input_el.get_attribute("id") or ""
            input_type = await input_el.get_attribute("type") or "text"
            placeholder = await input_el.get_attribute("placeholder") or ""
            if name and input_type not in ("hidden", "submit", "button"):
                fields.append({"name": name, "type": input_type, "placeholder": placeholder})
        if fields:
            forms.append({"action": action, "method": method, "fields": fields})
    return forms


async def _extract_search_links(page) -> list[dict]:
    """Extract search-related links from the rendered page."""
    links = []
    seen: set[str] = set()
    for a_el in await page.query_selector_all("a[href]"):
        href = await a_el.get_attribute("href") or ""
        text = (await a_el.text_content() or "").strip()
        if not text or not href or href in seen:
            continue
        if _SEARCH_LINK_RE.search(text + " " + href):
            seen.add(href)
            links.append({"text": text[:80], "url": href})
        if len(links) >= 10:
            break
    return links


def make_discover_forms_tool(ctx: BrowserContext, timeout_ms: int = _DEFAULT_PAGE_TIMEOUT_MS):
    """Create a discover_forms tool bound to a browser context."""

    @function_tool
    async def discover_forms(url: str) -> str:
        """Navigate to a URL and discover all forms and search-related links.

        Returns structured data — no raw HTML. Use this when submit_form
        fails and you need to find the correct form action and field names.
        """
        try:
            async with new_page(ctx, timeout_ms=timeout_ms) as page:
                try:
                    response = await page.goto(url, wait_until="domcontentloaded")
                except PlaywrightTimeout:
                    response = None
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightTimeout:
                    pass

                status_code = response.status if response else 0
                final_url = page.url

                forms = await _extract_forms(page)
                search_links = await _extract_search_links(page)

                # Resolve relative action URLs
                for form in forms:
                    if form["action"] and not form["action"].startswith("http"):
                        form["action"] = urljoin(final_url, form["action"])

                return json.dumps(
                    {
                        "status_code": status_code,
                        "final_url": final_url,
                        "forms": forms,
                        "search_links": search_links,
                    }
                )
        except PlaywrightTimeout:
            return json.dumps({"error": "Page navigation timed out"})
        except Exception as e:
            return json.dumps({"error": type(e).__name__})

    return discover_forms
