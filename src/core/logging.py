"""Structured logging with PII scrubbing.

Logs must never contain raw identity fields. This module sets up a logging
filter that catches accidental PII references in log messages and redacts
them. It is a defense-in-depth measure — code should not be logging PII in
the first place.
"""

import logging
import re
import sys
from typing import Any

from src.core.config import AppSettings

# Patterns for common PII shapes. These are deliberately broad — false positives
# (e.g. redacting a non-PII phone-shaped string) are preferable to leaks.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


class PIIScrubFilter(logging.Filter):
    """Redacts PII-shaped substrings in log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub_value(v) for k, v in record.args.items()}
            else:
                record.args = tuple(self._scrub_value(a) for a in record.args)
        return True

    @staticmethod
    def _scrub(text: str) -> str:
        text = _EMAIL_RE.sub("[email-redacted]", text)
        text = _PHONE_RE.sub("[phone-redacted]", text)
        text = _SSN_RE.sub("[ssn-redacted]", text)
        return text

    @classmethod
    def _scrub_value(cls, value: Any) -> Any:
        if isinstance(value, str):
            return cls._scrub(value)
        return value


def configure_logging(settings: AppSettings) -> None:
    """Set up the root logger. Called once at startup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(PIIScrubFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # Quiet down noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
