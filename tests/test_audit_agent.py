"""Tests for audit agent prompt, parsing, and execution."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.scan import FormFieldMatch
from src.services.audit.agent import audit_broker, load_prompt_template
from src.services.audit.parsing import extract_tool_metadata, parse_final_output


@dataclass
class FakeToolOutput:
    output: str


def test_prompt_template_loads_and_formats():
    template = load_prompt_template()
    assert "{broker_name}" in template
    result = template.format(
        broker_name="Spokeo",
        search_url="https://www.spokeo.com/search",
        identity_section="  - email: (provided)",
        input="  email: test@example.com",
    )
    assert "Spokeo" in result
    assert "test@example.com" in result


def test_extract_tool_metadata():
    items = [
        FakeToolOutput(output=json.dumps({"status_code": 200, "content_length": 5000})),
        FakeToolOutput(output=json.dumps({"error": "timeout"})),
    ]
    meta = extract_tool_metadata(items)
    assert meta["status_code"] == 200
    assert meta["content_length"] == 5000
    assert meta["message"] == "timeout"


def test_parse_final_output():
    raw = json.dumps({
        "status_code": 200,
        "content_length": 3000,
        "input_fields_found": ["name", "email"],
        "matched_inputs": [
            {"identity_field": "email", "form_input": "email", "found": True},
            {"identity_field": "name", "form_input": "name", "found": False},
        ],
    })
    meta = {"status_code": None, "content_length": None, "message": None}
    merged, fields, matches = parse_final_output(raw, meta)
    assert merged["status_code"] == 200
    assert fields == ["name", "email"]
    assert matches[0] == FormFieldMatch(identity_field="email", form_input="email", found=True)


def test_parse_found_values():
    """found: true → True, false → False, missing → None, non-bool → None."""
    for found_val, expected in [(True, True), (False, False), ("yes", None)]:
        raw = json.dumps({"matched_inputs": [
            {"identity_field": "email", "form_input": "email", "found": found_val},
        ]})
        meta = {"status_code": None, "content_length": None, "message": None}
        _, _, matches = parse_final_output(raw, meta)
        assert matches[0].found is expected


def _mock_settings(**overrides):
    s = MagicMock()
    s.agent_timeout_seconds = overrides.get("agent_timeout_seconds", 30)
    s.openai_model = overrides.get("openai_model", "gpt-4o-mini")
    return s


@pytest.mark.asyncio
async def test_audit_broker_timeout():
    async def slow_runner(*args, **kwargs):
        await asyncio.sleep(10)

    mock_ctx = AsyncMock()
    with (
        patch("src.services.audit.agent.Runner.run", side_effect=slow_runner),
        patch("src.services.audit.agent.browser_context") as mock_bc,
    ):
        mock_bc.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_bc.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await audit_broker(
            "TestBroker", "https://example.com/search",
            settings=_mock_settings(agent_timeout_seconds=0.1),
        )
    assert result.message == "Completed at timeout."
    assert result.name == "TestBroker"


@pytest.mark.asyncio
async def test_audit_broker_success():
    class FakeResult:
        final_output = json.dumps({
            "status_code": 200, "content_length": 3000,
            "input_fields_found": ["email"], "matched_inputs": [],
        })
        new_items = []

    mock_ctx = MagicMock()
    with (
        patch("src.services.audit.agent.Runner.run", new_callable=AsyncMock, return_value=FakeResult()),
        patch("src.services.audit.agent.browser_context") as mock_bc,
    ):
        mock_bc.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_bc.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await audit_broker(
            "TestBroker", "https://example.com/search", settings=_mock_settings(),
        )
    assert result.message is None
    assert result.status_code == 200
