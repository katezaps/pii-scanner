"""Pydantic API schemas for /audit endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RunAuditAgentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    broker_keys: list[str] = Field(min_length=1, max_length=100)
    save: bool
    scan_name: str | None = Field(default=None, max_length=100)
    email: str | None = None
    phone: str | None = None
    name: str | None = None
    address: str | None = None


class FormFieldMatchOut(BaseModel):
    identity_field: str
    form_input: str
    found: bool | None = None


class AuditAgentResultOut(BaseModel):
    name: str
    search_url: str
    status_code: int | None
    content_length: int | None
    message: str | None
    input_fields_found: list[str]
    matched_inputs: list[FormFieldMatchOut]
    opt_out_url: str | None = None


class AcceptedField(BaseModel):
    field_type: str
    status: str
