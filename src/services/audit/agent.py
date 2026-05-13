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

import json

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
from src.services.tools import build_tools, make_find_opt_out_tool

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


async def _run_opt_out_discovery(
    ctx: BrowserContext,
    name: str,
    search_url: str,
    settings: AppSettings,
) -> str | None:
    """Run a separate agent to discover the opt-out URL for a broker."""
    timeout_ms = settings.page_timeout_seconds * 1000
    agent = Agent(
        name=f"opt-out-{name}",
        model=settings.openai_model,
        instructions=(
            "You are discovering the data opt-out or removal page for a data broker. "
            "Call find_opt_out on the URL provided and report the results as JSON."
        ),
        tools=[make_find_opt_out_tool(ctx, timeout_ms=timeout_ms * 2)],
    )
    try:
        result = await Runner.run(agent, input=f"Find the opt-out page for {search_url}")
        for item in result.new_items:
            if hasattr(item, "output") and isinstance(item.output, str):
                try:
                    tool_out = json.loads(item.output)
                    pages = tool_out.get("opt_out_pages", [])
                    if pages and isinstance(pages[0], dict):
                        return pages[0].get("url")
                except (json.JSONDecodeError, TypeError):
                    pass
    except Exception as e:
        logger.debug("opt-out discovery failed for %s: %s", name, e)
    return None


async def audit_broker(
    name: str,
    search_url: str,
    identity: dict[str, str] | None = None,
    *,
    settings: AppSettings,
    db_opt_out_url: str | None = None,
) -> AuditAgentResult:
    """Run a scan agent and opt-out discovery agent in parallel."""
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

        # Run opt-out discovery in parallel if not cached
        opt_out_task = None
        if db_opt_out_url is None:
            opt_out_task = asyncio.create_task(
                _run_opt_out_discovery(ctx, name, search_url, settings)
            )

        pending = {runner_task}
        if opt_out_task is not None:
            pending.add(opt_out_task)

        try:
            done, still_pending = await asyncio.wait(pending, timeout=timeout)

            # Resolve opt-out URL: cached > discovered > None
            opt_out_url = db_opt_out_url
            if opt_out_task is not None:
                if opt_out_task in done:
                    opt_out_url = opt_out_task.result()
                else:
                    opt_out_task.cancel()
                    try:
                        await opt_out_task
                    except (asyncio.CancelledError, Exception):
                        pass  # noqa: S110

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
                    opt_out_url=opt_out_url,
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
                opt_out_url=opt_out_url,
            )

        except asyncio.CancelledError:
            # Scan-level cancellation
            try:
                await ctx.close()
            except Exception:
                pass  # noqa: S110
            runner_task.cancel()
            if opt_out_task is not None:
                opt_out_task.cancel()
            for t in [runner_task, opt_out_task]:
                if t is not None:
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass  # noqa: S110
            return AuditAgentResult(
                name=name,
                search_url=search_url,
                status_code=None,
                content_length=None,
                message="Completed at timeout.",
                matched_inputs=partial_to_matches(partial_results),
                opt_out_url=db_opt_out_url,
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
                opt_out_url=db_opt_out_url,
            )
