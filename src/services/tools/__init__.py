"""Agent tools for discovering forms and submitting searches.

``build_tools`` is the primary entry point — it returns the appropriate
tool list based on whether identity fields are provided.
"""

from __future__ import annotations

from playwright.async_api import BrowserContext

from src.services.tools.discover_forms import make_discover_forms_tool
from src.services.tools.find_opt_out import make_find_opt_out_tool
from src.services.tools.pii import check_pii_in_body
from src.services.tools.submit_form import make_submit_form_tool

__all__ = [
    "check_pii_in_body",
    "make_discover_forms_tool",
    "make_find_opt_out_tool",
    "make_submit_form_tool",
    "build_tools",
]


def build_tools(
    ctx: BrowserContext,
    identity: dict[str, str] | None = None,
    page_timeout_seconds: int = 30,
    partial_results: dict[str, bool] | None = None,
) -> list:
    """Return the tool list for a scan agent.

    Always includes ``discover_forms``. If identity fields are provided,
    also includes a ``submit_form`` tool configured with PII matching.
    Opt-out discovery runs as a separate parallel agent — not included here.
    """
    timeout_ms = page_timeout_seconds * 1000
    tools = [
        make_discover_forms_tool(ctx, timeout_ms=timeout_ms),
    ]
    if identity:
        tools.append(
            make_submit_form_tool(
                ctx,
                identity,
                timeout_ms=timeout_ms,
                partial_results=partial_results,
            )
        )
    return tools
