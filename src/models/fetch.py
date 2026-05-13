"""Request and response models for /fetch."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.models.enums import ScanState


class FetchResult(BaseModel):
    """A single stored result returned from /fetch."""

    broker_id: UUID
    broker_key: str
    broker_name: str
    search_url: str
    field_type: str
    state: ScanState
    found: bool
    message: str | None = None
    opt_out_url: str | None = None


class FetchSummary(BaseModel):
    total_brokers_scanned: int
    total_results: int
    found_count: int


class FetchResponse(BaseModel):
    execution_id: UUID
    name: str | None
    broker_version: int
    expires_at: datetime
    results: list[FetchResult]
    summary: FetchSummary


class ScanListItem(BaseModel):
    execution_id: UUID
    name: str | None
    state: ScanState
    expires_at: datetime
    broker_count: int
    found_count: int
    incomplete_count: int


class ScanListResponse(BaseModel):
    scans: list[ScanListItem]
