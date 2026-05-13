"""find_opt_out tool — scans a broker site for a data opt-out page.

Crawls the broker site looking for opt-out or data-removal links,
then probes common opt-out URL paths. Database caching is handled
by the caller — this tool is pure discovery.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urljoin

from agents import function_tool
from playwright.async_api import BrowserContext
from playwright.async_api import TimeoutError as PlaywrightTimeout

from src.services.browser import new_page

logger = logging.getLogger(__name__)

_DEFAULT_PAGE_TIMEOUT_MS = 30_000

# Patterns that indicate an opt-out or data-removal page.
_OPT_OUT_RE = re.compile(
    r"opt.?out|remove|deletion|do.not.sell|suppress|privacy.?rights"
    r"|data.?removal|erase|right.to.delete|ccpa|your.?data"
    r"|manage.?your.?info|control.?your.?data",
    re.IGNORECASE,
)

# Common opt-out URL paths that brokers use.
_COMMON_PATHS = [
    "/optout",
    "/opt-out",
    "/remove",
    "/removal",
    "/suppression",
    "/do-not-sell",
    "/privacy",
    "/privacy-rights",
    "/data-removal",
]


async def _find_opt_out_links(page, base_url: str) -> list[dict]:
    """Extract links whose text or href suggest an opt-out page."""
    links: list[dict] = []
    seen: set[str] = set()
    for a_el in await page.query_selector_all("a[href]"):
        href = await a_el.get_attribute("href") or ""
        text = (await a_el.text_content() or "").strip()
        if not href or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        full_url = urljoin(base_url, href)
        if full_url in seen:
            continue
        if _OPT_OUT_RE.search(text + " " + href):
            seen.add(full_url)
            links.append({"text": text[:120], "url": full_url})
        if len(links) >= 10:
            break
    return links


async def _probe_common_paths(
    ctx: BrowserContext, base_url: str, timeout_ms: int
) -> list[dict]:
    """Try common opt-out URL paths and return any that resolve (non-4xx)."""
    hits: list[dict] = []
    for path in _COMMON_PATHS:
        url = urljoin(base_url, path)
        try:
            async with new_page(ctx, timeout_ms=timeout_ms) as page:
                response = await page.goto(url, wait_until="domcontentloaded")
                if response and response.status < 400:
                    title = await page.title() or ""
                    hits.append({
                        "url": page.url,
                        "status_code": response.status,
                        "title": title[:120],
                    })
        except (PlaywrightTimeout, Exception):
            continue
        if len(hits) >= 5:
            break
    return hits


def make_find_opt_out_tool(ctx: BrowserContext, timeout_ms: int = _DEFAULT_PAGE_TIMEOUT_MS):
    """Create a find_opt_out tool bound to a browser context."""

    @function_tool
    async def find_opt_out(url: str) -> str:
        """Scan a broker site for data opt-out or removal pages.

        Crawls the site for links matching opt-out patterns, then probes
        common opt-out URL paths. Database caching is handled by the caller.

        Args:
            url: The broker site URL to scan (e.g. the homepage or privacy page).
        """
        opt_out_links: list[dict] = []

        try:
            async with new_page(ctx, timeout_ms=timeout_ms) as page:
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                except PlaywrightTimeout:
                    pass
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeout:
                    pass

                opt_out_links = await _find_opt_out_links(page, page.url)
        except Exception as e:
            logger.debug("find_opt_out link scan failed for %s: %s", url, e)

        try:
            probed = await _probe_common_paths(ctx, url, timeout_ms)
            seen_urls = {link["url"] for link in opt_out_links}
            for hit in probed:
                if hit["url"] not in seen_urls:
                    opt_out_links.append({
                        "text": str(hit.get("title", "")),
                        "url": hit["url"],
                        "source": "probed_path",
                    })
        except Exception as e:
            logger.debug("find_opt_out path probing failed for %s: %s", url, e)

        return json.dumps({
            "scanned_url": url,
            "opt_out_pages": opt_out_links,
            "found": len(opt_out_links) > 0,
        })

    return find_opt_out
