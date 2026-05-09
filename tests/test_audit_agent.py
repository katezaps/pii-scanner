"""Tests for audit agent prompt, parsing, and execution."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.scan import FormFieldMatch
from src.services.audit.agent import audit_broker, build_prompt, load_prompt_template
from src.services.audit.parsing import extract_tool_metadata, parse_final_output


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


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
    assert "response body is never exposed" in result


def test_build_prompt_excludes_pii_values():
    prompt = build_prompt("https://example.com/search", {"email": "x@y.com", "phone": "+1234"})
    assert "x@y.com" not in prompt
    assert "+1234" not in prompt
    assert "email" in prompt


# ---------------------------------------------------------------------------
# extract_tool_metadata
# ---------------------------------------------------------------------------


@dataclass
class FakeToolOutput:
    output: str


def test_extract_tool_metadata_success_and_error():
    items = [
        FakeToolOutput(output=json.dumps({"status_code": 200, "content_length": 5000})),
        FakeToolOutput(output=json.dumps({"error": "timeout"})),
    ]
    meta = extract_tool_metadata(items)
    assert meta["status_code"] == 200
    assert meta["content_length"] == 5000
    assert meta["message"] == "timeout"


def test_extract_tool_metadata_rejects_wrong_types():
    items = [
        FakeToolOutput(output=json.dumps({"status_code": "200", "content_length": False})),
    ]
    meta = extract_tool_metadata(items)
    assert meta["status_code"] is None
    assert meta["content_length"] is None


def test_extract_tool_metadata_handles_invalid_input():
    assert extract_tool_metadata([]) == {"status_code": None, "content_length": None, "message": None}
    assert extract_tool_metadata([FakeToolOutput(output="not json")]) == {"status_code": None, "content_length": None, "message": None}
    assert extract_tool_metadata([object()]) == {"status_code": None, "content_length": None, "message": None}


# ---------------------------------------------------------------------------
# parse_final_output
# ---------------------------------------------------------------------------


def test_parse_final_output_full():
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


def test_parse_final_output_invalid_json():
    meta = {"status_code": 200, "content_length": 100, "message": None}
    merged, fields, matches = parse_final_output("not json", meta)
    assert merged["message"] == "invalid agent response format"
    assert fields == []
    assert matches == []


def test_parse_final_output_skips_malformed_matches():
    raw = json.dumps({
        "matched_inputs": [
            {"identity_field": "email", "form_input": "email"},
            {"bad": "data"},
            "not a dict",
            {"identity_field": 123, "form_input": "email"},
        ],
    })
    meta = {"status_code": None, "content_length": None, "message": None}
    _, _, matches = parse_final_output(raw, meta)
    assert len(matches) == 1
    assert matches[0].identity_field == "email"


def test_parse_found_values():
    """found: true → True, false → False, missing → None, non-bool → None."""
    for found_val, expected in [(True, True), (False, False), ("yes", None)]:
        raw = json.dumps({"matched_inputs": [
            {"identity_field": "email", "form_input": "email", "found": found_val},
        ]})
        meta = {"status_code": None, "content_length": None, "message": None}
        _, _, matches = parse_final_output(raw, meta)
        assert matches[0].found is expected

    # missing found key
    raw = json.dumps({"matched_inputs": [{"identity_field": "email", "form_input": "email"}]})
    _, _, matches = parse_final_output(raw, {"status_code": None, "content_length": None, "message": None})
    assert matches[0].found is None


# ---------------------------------------------------------------------------
# audit_broker execution
# ---------------------------------------------------------------------------


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


@pytest.mark.asyncio
async def test_scan_timeout_cancels_slow_brokers():
    from src.models.scan import AuditAgentResult
    from src.services.audit.orchestrator import stream_audit_agents

    async def slow_broker(*args, **kwargs):
        await asyncio.sleep(60)
        return AuditAgentResult(
            name="SlowBroker", search_url="https://slow.example.com",
            status_code=200, content_length=100, message=None,
        )

    mock_settings = _mock_settings(agent_timeout_seconds=0.2)
    with (
        patch("src.services.audit.orchestrator.audit_broker", side_effect=slow_broker),
        patch("src.services.audit.orchestrator.resolve_brokers", new_callable=AsyncMock,
              return_value=[{"name": "SlowBroker", "search_url": "https://slow.example.com"}]),
    ):
        results = []
        async for r in stream_audit_agents(broker_keys=["slow"], settings=mock_settings):
            results.append(r)
    assert len(results) == 1
    assert results[0].message == "Cancelled."
