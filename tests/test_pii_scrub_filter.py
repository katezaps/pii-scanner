"""Tests for PIIScrubFilter — ensures PII is redacted from logs."""

from __future__ import annotations

import logging

from src.core.logging import PIIScrubFilter


def test_scrubs_email_phone_ssn():
    f = PIIScrubFilter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "user@example.com 555-123-4567 123-45-6789", (), None)
    f.filter(record)
    assert "user@example.com" not in record.getMessage()
    assert "555-123-4567" not in record.getMessage()
    assert "123-45-6789" not in record.getMessage()


def test_filter_never_suppresses():
    f = PIIScrubFilter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "clean message", (), None)
    assert f.filter(record) is True
