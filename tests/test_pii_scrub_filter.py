"""Tests for PIIScrubFilter — defense-in-depth log redaction."""

from __future__ import annotations

import logging

from src.core.logging import PIIScrubFilter


def _make_record(msg: str, args=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg=msg, args=args, exc_info=None,
    )


_filter = PIIScrubFilter()


def test_scrubs_email_phone_ssn():
    record = _make_record("user test@x.com phone +12125550101 ssn 123-45-6789")
    _filter.filter(record)
    assert "test@x.com" not in record.msg
    assert "2125550101" not in record.msg
    assert "123-45-6789" not in record.msg
    assert "[email-redacted]" in record.msg
    assert "[phone-redacted]" in record.msg


def test_scrubs_args():
    record = _make_record("user=%s email=%s", ("alice", "alice@example.com"))
    _filter.filter(record)
    assert record.args[0] == "alice"
    assert record.args[1] == "[email-redacted]"


def test_no_pii_unchanged():
    msg = "Broker scan completed for testbroker in 3.2s"
    record = _make_record(msg)
    _filter.filter(record)
    assert record.msg == msg


def test_filter_never_suppresses():
    record = _make_record("has pii: test@example.com")
    assert _filter.filter(record) is True
