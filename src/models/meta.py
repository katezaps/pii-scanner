"""Request and response models for /me, /login, /signup, /health."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MeResponse(BaseModel):
    user_id: UUID
    name: str | None
    token_id: UUID
    token_name: str | None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    user_id: UUID
    name: str


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)


class SignupResponse(BaseModel):
    user_id: UUID
    name: str


class HealthResponse(BaseModel):
    status: str = "ok"
    broker_version: int
    agent_timeout_seconds: int
