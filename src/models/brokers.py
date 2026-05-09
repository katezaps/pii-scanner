"""Request and response models for /brokers."""

from datetime import datetime

from pydantic import BaseModel


class BrokerOut(BaseModel):
    version: int
    key: str
    name: str
    search_url: str
    created_at: datetime


class BrokersResponse(BaseModel):
    version: int
    brokers: list[BrokerOut]
