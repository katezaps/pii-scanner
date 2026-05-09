"""Domain models for scan results (used by the services layer)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class FormFieldMatch:
    identity_field: str
    form_input: str
    found: bool | None = None


@dataclass(frozen=True, slots=True)
class AuditAgentResult:
    name: str
    search_url: str
    status_code: int | None
    content_length: int | None
    message: str | None
    input_fields_found: list[str] = field(default_factory=list)
    matched_inputs: list[FormFieldMatch] = field(default_factory=list)
