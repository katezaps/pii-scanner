"""Shared enums used across API models."""

from enum import StrEnum


class ScanState(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
