"""Request and response models for /brokers."""

from datetime import datetime

from pydantic import BaseModel


class BrokerOut(BaseModel):
    version: int
    key: str
    name: str
    search_url: str
    created_at: datetime
    opt_out_url: str | None = None
    opt_out_url_source: str | None = None


class BrokersResponse(BaseModel):
    version: int
    brokers: list[BrokerOut]
