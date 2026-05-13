"""Tests for agent tools — PII matching, discover_forms, submit_form."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agents.tool import ToolContext

from src.services.tools import (
    build_tools,
    check_pii_in_body,
    make_discover_forms_tool,
    make_submit_form_tool,
)


def _tool_ctx(args: str = "{}"):
    return ToolContext(
        context=None, tool_name="test", tool_call_id="test-1", tool_arguments=args,
    )


def test_pii_matching():
    body = "<html>Jane A. Doe - jane@example.com - +15551234567</html>"
    identity = {"email": "jane@example.com", "name": "Jane Doe", "phone": "+15551234567"}
    result = check_pii_in_body(body, identity)
    assert result == {"email": True, "name": True, "phone": True}

    assert check_pii_in_body("<html>No results</html>", {"email": "x@y.com"}) == {"email": False}


def test_build_tools_count():
    ctx = MagicMock()
    assert len(build_tools(ctx)) == 1  # discover_forms only
    assert len(build_tools(ctx, {"email": "test@example.com"})) == 2  # + submit_form


def _mock_page(*, content="<html></html>", url="https://example.com", status=200):
    page = AsyncMock()
    page.url = url
    page.content = AsyncMock(return_value=content)
    response = MagicMock()
    response.status = status
    page.goto = AsyncMock(return_value=response)
    return page


@contextmanager
def _patch_new_page(page):
    @asynccontextmanager
    async def fake(ctx, **kwargs):
        yield page

    with (
        patch("src.services.tools.discover_forms.new_page", side_effect=fake),
        patch("src.services.tools.submit_form.new_page", side_effect=fake),
    ):
        yield


@pytest.mark.asyncio
async def test_discover_forms():
    ctx = MagicMock()
    page = _mock_page(url="https://example.com/search", status=200)

    form = AsyncMock()
    form.get_attribute = AsyncMock(side_effect=lambda a: {"action": "/search", "method": "GET"}.get(a, ""))
    input_el = AsyncMock()
    input_el.get_attribute = AsyncMock(side_effect=lambda a: {"name": "q", "type": "text", "placeholder": "Search"}.get(a, ""))
    form.query_selector_all = AsyncMock(return_value=[input_el])

    link = AsyncMock()
    link.get_attribute = AsyncMock(return_value="https://example.com/phone")
    link.text_content = AsyncMock(return_value="Search by Phone")

    page.query_selector_all = AsyncMock(side_effect=lambda sel: [form] if sel == "form" else [link])
    page.wait_for_load_state = AsyncMock()

    with _patch_new_page(page):
        tool = make_discover_forms_tool(ctx)
        result = json.loads(await tool.on_invoke_tool(_tool_ctx(), '{"url": "https://example.com/search"}'))

    assert len(result["forms"]) == 1
    assert result["forms"][0]["fields"][0]["name"] == "q"
    assert "body" not in result


@pytest.mark.asyncio
async def test_submit_form_body_never_returned():
    """Critical security invariant."""
    ctx = MagicMock()
    body = "<html>secret@example.com and sensitive data</html>"
    page = _mock_page(content=body, url="https://broker.com/results", status=200)

    with _patch_new_page(page):
        tool = make_submit_form_tool(ctx, {"email": "secret@example.com"})
        params = json.dumps({"url": "https://broker.com/search", "method": "GET", "params": '{"q": "test"}'})
        raw = await tool.on_invoke_tool(_tool_ctx(), params)

    assert "secret@example.com" not in raw
    assert "sensitive data" not in raw
