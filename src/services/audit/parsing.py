"""Parsing and validation for audit agent responses."""

from __future__ import annotations

import json
import logging

from src.models.scan import FormFieldMatch

logger = logging.getLogger(__name__)


def _validate_int_or_none(value: object, field_name: str) -> int | None:
    """Return an int if value is a valid int, None if null, or None with a warning."""
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    logger.warning("Invalid %s: expected int or null, got %r", field_name, type(value).__name__)
    return None


def _validate_str_or_none(value: object, field_name: str) -> str | None:
    """Return a str if value is a valid string, None if null, or None with a warning."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    logger.warning("Invalid %s: expected string or null, got %r", field_name, type(value).__name__)
    return None


def extract_tool_metadata(items) -> dict:
    """Extract status_code, content_length, and message from tool call outputs."""
    status_code = None
    content_length = None
    message = None

    for item in items:
        if hasattr(item, "output") and isinstance(item.output, str):
            try:
                parsed = json.loads(item.output)
                if "status_code" in parsed and status_code is None:
                    status_code = _validate_int_or_none(parsed["status_code"], "status_code")
                if "content_length" in parsed and content_length is None:
                    content_length = _validate_int_or_none(
                        parsed["content_length"], "content_length"
                    )
                if "error" in parsed and message is None:
                    message = _validate_str_or_none(parsed["error"], "error")
            except (json.JSONDecodeError, TypeError):
                pass

    return {
        "status_code": status_code,
        "content_length": content_length,
        "message": message,
    }


def parse_final_output(raw_output: str, meta: dict) -> tuple[dict, list[str], list[FormFieldMatch]]:
    """Parse the agent's final JSON response into structured data.

    Returns (merged_meta, input_fields_found, matched_inputs).
    If the output is not valid JSON or not a dict, sets error to
    "invalid agent response format".
    """
    status_code = meta["status_code"]
    content_length = meta["content_length"]
    message = meta["message"]
    input_fields_found: list[str] = []
    matched_inputs: list[FormFieldMatch] = []

    try:
        final = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Agent output is not valid JSON: %s", raw_output[:200])
        if message is None:
            message = "invalid agent response format"
        merged = {
            "status_code": status_code,
            "content_length": content_length,
            "message": message,
        }
        return merged, input_fields_found, matched_inputs

    if not isinstance(final, dict):
        logger.warning("Agent output is not a JSON object: %s", type(final).__name__)
        if message is None:
            message = "invalid agent response format"
        merged = {
            "status_code": status_code,
            "content_length": content_length,
            "message": message,
        }
        return merged, input_fields_found, matched_inputs

    if "status_code" in final and status_code is None:
        status_code = _validate_int_or_none(final["status_code"], "status_code")
    if "content_length" in final and content_length is None:
        content_length = _validate_int_or_none(final["content_length"], "content_length")
    if "error" in final and message is None:
        message = _validate_str_or_none(final["error"], "error")

    if "input_fields_found" in final:
        if not isinstance(final["input_fields_found"], list):
            logger.warning("input_fields_found is not a list")
        else:
            input_fields_found = [str(f) for f in final["input_fields_found"] if isinstance(f, str)]

    if "matched_inputs" in final:
        if not isinstance(final["matched_inputs"], list):
            logger.warning("matched_inputs is not a list")
        else:
            for m in final["matched_inputs"]:
                if (
                    isinstance(m, dict)
                    and isinstance(m.get("identity_field"), str)
                    and isinstance(m.get("form_input"), str)
                ):
                    found_val = m.get("found")
                    if not isinstance(found_val, bool):
                        found_val = None
                    matched_inputs.append(
                        FormFieldMatch(
                            identity_field=m["identity_field"],
                            form_input=m["form_input"],
                            found=found_val,
                        )
                    )

    merged = {
        "status_code": status_code,
        "content_length": content_length,
        "message": message,
    }
    return merged, input_fields_found, matched_inputs


def partial_to_matches(partial_results: dict[str, bool]) -> list[FormFieldMatch]:
    """Convert a partial_results accumulator into FormFieldMatch objects."""
    return [
        FormFieldMatch(identity_field=field, form_input=field, found=found)
        for field, found in partial_results.items()
    ]
