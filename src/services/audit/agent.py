"""Single-broker audit agent — construction, execution, and timeout handling.

Each broker gets its own agent that dynamically explores the broker's
search page — fetching HTML, discovering forms, following links when
needed — and reports which identity fields the site accepts.

Agents adapt their strategy per site: some brokers have a single search
bar, others split name/phone/email into separate pages, others use
JavaScript-rendered forms. Tools use a headless browser (Playwright)
so agents see fully rendered page content including dynamic elements.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from pathlib import Path

from agents import Agent, Runner
from playwright.async_api import BrowserContext

from src.core.config import AppSettings
from src.models.scan import AuditAgentResult
from src.services.audit.parsing import (
    extract_tool_metadata,
    parse_final_output,
    partial_to_matches,
)
from src.services.browser import browser_context
from src.services.tools import build_tools

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "audit_agent.md"


@lru_cache(maxsize=1)
def load_prompt_template() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _make_agent(
    broker_name: str,
    search_url: str,
    identity: dict[str, str] | None = None,
    *,
    ctx: BrowserContext,
    settings: AppSettings,
    partial_results: dict[str, bool] | None = None,
) -> Agent:
    identity_section = ""
    pii_input = "None provided"
    if identity:
        field_descriptions = "\n".join(f"  - {k}: (provided)" for k in identity)
        identity_section = "Identity fields to check for:\n" + field_descriptions
        pii_input = "\n".join(f"  {k}: {v}" for k, v in identity.items())

    instructions = load_prompt_template().format(
        broker_name=broker_name,
        search_url=search_url,
        identity_section=identity_section,
        input=pii_input,
    )

    return Agent(
        name=f"audit-{broker_name}",
        model=settings.openai_model,
        instructions=instructions,
        tools=build_tools(
            ctx,
            identity,
            page_timeout_seconds=settings.page_timeout_seconds,
            partial_results=partial_results,
        ),
    )


def build_prompt(search_url: str, identity: dict[str, str] | None) -> str:
    """Construct the prompt sent to the agent."""
    prompt = f"Explore {search_url} and find all form inputs the site uses for people searches."
    if identity:
        fields = ", ".join(identity.keys())
        prompt += (
            f" Determine which of these identity fields have matching "
            f"form inputs on the site: {fields}."
        )
    prompt += " Respond with JSON only."
    return prompt


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------


async def audit_broker(
    name: str,
    search_url: str,
    identity: dict[str, str] | None = None,
    *,
    settings: AppSettings,
) -> AuditAgentResult:
    """Run a single agent against one broker and return structured results."""
    timeout = settings.agent_timeout_seconds
    partial_results: dict[str, bool] = {}

    async with browser_context() as ctx:
        agent = _make_agent(
            name,
            search_url,
            identity,
            ctx=ctx,
            settings=settings,
            partial_results=partial_results,
        )
        prompt = build_prompt(search_url, identity)
        runner_task = asyncio.create_task(Runner.run(agent, input=prompt))

        try:
            done, _ = await asyncio.wait({runner_task}, timeout=timeout)

            if runner_task in done:
                result = runner_task.result()
                logger.info(
                    "audit agent broker=%s output=%s",
                    name,
                    result.final_output,
                )

                meta = extract_tool_metadata(result.new_items)
                meta, input_fields_found, matched_inputs = (
                    parse_final_output(result.final_output, meta)
                )

                return AuditAgentResult(
                    name=name,
                    search_url=search_url,
                    status_code=meta["status_code"],
                    content_length=meta["content_length"],
                    message=meta["message"],
                    input_fields_found=input_fields_found,
                    matched_inputs=matched_inputs,
                )

            # Timeout — force-close browser context to kill Playwright,
            # then cancel the runner task.
            logger.warning(
                "audit agent broker=%s timed out after %ds", name, timeout
            )
            try:
                await ctx.close()
            except Exception:
                pass  # noqa: S110
            runner_task.cancel()
            try:
                await runner_task
            except (asyncio.CancelledError, Exception):
                pass  # noqa: S110
            return AuditAgentResult(
                name=name,
                search_url=search_url,
                status_code=None,
                content_length=None,
                message="Completed at timeout.",
                matched_inputs=partial_to_matches(partial_results),
            )

        except asyncio.CancelledError:
            # Scan-level cancellation
            try:
                await ctx.close()
            except Exception:
                pass  # noqa: S110
            runner_task.cancel()
            try:
                await runner_task
            except (asyncio.CancelledError, Exception):
                pass  # noqa: S110
            return AuditAgentResult(
                name=name,
                search_url=search_url,
                status_code=None,
                content_length=None,
                message="Completed at timeout.",
                matched_inputs=partial_to_matches(partial_results),
            )

        except Exception as e:
            logger.warning("audit agent broker=%s failed: %s", name, e)
            return AuditAgentResult(
                name=name,
                search_url=search_url,
                status_code=None,
                content_length=None,
                message=str(e),
                matched_inputs=partial_to_matches(partial_results),
            )
