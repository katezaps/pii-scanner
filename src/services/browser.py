"""Shared Playwright browser lifecycle.

Provides a singleton browser instance and helpers for creating
isolated contexts and pages with bounded concurrency.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

_playwright: Playwright | None = None
_browser: Browser | None = None
_lock = asyncio.Lock()

# Limit concurrent browser contexts to prevent OOM under load.
# Each context ≈ 50-100MB with a page open.
_context_semaphore = asyncio.Semaphore(5)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


async def get_browser() -> Browser:
    """Return the singleton browser, launching it on first call."""
    global _playwright, _browser
    async with _lock:
        if _browser is None or not _browser.is_connected():
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(
                headless=True,
                args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"],
            )
    return _browser


async def shutdown_browser() -> None:
    """Close browser and Playwright. Call on app shutdown."""
    global _playwright, _browser
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None


@asynccontextmanager
async def browser_context() -> AsyncIterator[BrowserContext]:
    """Create an isolated browser context (fresh cookies/storage).

    Gated by a semaphore to limit concurrent contexts and prevent OOM.
    """
    async with _context_semaphore:
        br = await get_browser()
        ctx = await br.new_context(user_agent=_USER_AGENT)
        try:
            yield ctx
        finally:
            try:
                await ctx.close()
            except Exception:
                pass  # already closed (e.g. force-closed on timeout)


@asynccontextmanager
async def new_page(ctx: BrowserContext, timeout_ms: int = 30_000) -> AsyncIterator[Page]:
    """Create a page within a context."""
    page = await ctx.new_page()
    page.set_default_timeout(timeout_ms)
    page.set_default_navigation_timeout(timeout_ms)
    try:
        yield page
    finally:
        await page.close()
