"""Provider-neutral observations; missing fields stay missing."""
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

class Bar(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    feed: str

class OptionObservation(BaseModel):
    symbol: str
    underlying: str
    expiration: date
    kind: Literal["call", "put"]
    strike: float = Field(gt=0)
    source: str
    feed: str
    quote_timestamp: datetime | None = None
    retrieved_at: datetime
    bid: float | None = None
    ask: float | None = None
    bid_exchange: str | None = None
    ask_exchange: str | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    classification: str = "current"
