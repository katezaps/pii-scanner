"""PII matching utilities.

Uses token-based matching for names and exact matching for structured
fields (email, phone, address). This handles common reformatting by
brokers — e.g. "Jane Doe" matching "Jane A. Doe" or "Doe, Jane".
"""

from __future__ import annotations

import re

# Fields where every token must appear independently (order-insensitive)
_TOKEN_MATCH_FIELDS = {"name"}

# Minimum token length to avoid matching single-letter fragments
_MIN_TOKEN_LEN = 2


def _tokenize(value: str) -> list[str]:
    """Split a value into lowercase alpha tokens, filtering short ones."""
    return [
        t for t in re.split(r"[^a-zA-Z]+", value.lower()) if len(t) >= _MIN_TOKEN_LEN
    ]


def _token_match(value: str, body_lower: str) -> bool:
    """Return True if every meaningful token of value appears in body."""
    tokens = _tokenize(value)
    if not tokens:
        return False
    return all(token in body_lower for token in tokens)


def check_pii_in_body(body: str, identity: dict[str, str]) -> dict[str, bool]:
    """Check which PII values appear in a response body.

    - For name fields: token-based matching (each word must appear
      independently, catching "Jane A. Doe", "Doe, Jane", etc.)
    - For email/phone/address: exact substring matching (case-insensitive)
    """
    body_lower = body.lower()
    result: dict[str, bool] = {}
    for field_type, value in identity.items():
        if field_type in _TOKEN_MATCH_FIELDS:
            result[field_type] = _token_match(value, body_lower)
        else:
            result[field_type] = value.lower() in body_lower
    return result
