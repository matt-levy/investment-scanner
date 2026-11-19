import os
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from .analytics import realized_volatility
from .ranking import screen_factors
from .db import Contract, IngestionRun, Security, Session
from .market_db import MarketBar, MarketOptionQuote
from .market_providers import AlpacaProvider, MarketDataProvider
from .market_service import compare, persist_bar, persist_quote, serialize_quote
from .provider import ProviderError

router = APIRouter()

def selected_provider():
    name = os.getenv("PRIMARY_MARKET_DATA_PROVIDER", "alpaca").lower()
    if name not in ("alpaca", "alphavantage"):
        raise HTTPException(503, "Unsupported primary market data provider.")
    return name

def get_security(db, ticker):
    sec = db.scalar(select(Security).where(Security.ticker == ticker.upper()))
    if not sec:
        raise HTTPException(404, "Ticker is outside the configured universe.")
    return sec

@router.post("/ingest/{ticker}")
async def ingest_market(ticker: str):
    if selected_provider() == "alphavantage":
        from .main import ingest
        return await ingest(ticker)
    with Session() as db:
        ticker = get_security(db, ticker).ticker
    try:
        provider = AlpacaProvider()
        bars = await provider.bars(ticker)
        chain = await provider.chain(ticker)
        if not bars or not chain:
            raise ProviderError("Alpaca returned incomplete bars or an empty options chain; no data was saved.")
        with Session.begin() as db:
            sec = get_security(db, ticker)
            for bar in bars:
                persist_bar(db, sec, bar)
            count = sum(persist_quote(db, sec, observation) for observation in chain)
            db.add(IngestionRun(ticker=ticker, status="success", message=f"alpaca: saved {count} new observations"))
        return {"ticker": ticker, "source": "alpaca", "feed": provider.option_feed, "new_option_quotes": count}
    except (ProviderError, ValueError) as exc:
        with Session.begin() as db:
            db.add(IngestionRun(ticker=ticker, status="error", message=str(exc)[:500]))
        raise HTTPException(503, str(exc)) from exc

@router.get("/securities/{ticker}")
def market_detail(ticker: str):
    if selected_provider() == "alphavantage":
        from .main import detail
        return detail(ticker)
    with Session() as db:
        sec = get_security(db, ticker)
        bars = list(db.scalars(select(MarketBar).where(MarketBar.security_id == sec.id, MarketBar.source == "alpaca", MarketBar.feed == os.getenv("ALPACA_STOCK_FEED", "iex")).order_by(MarketBar.timestamp)))
        run = db.scalar(select(IngestionRun).where(IngestionRun.ticker == sec.ticker).order_by(IngestionRun.id.desc()))
        return {"ticker": sec.ticker, "prices": [{"date": b.timestamp.date(), "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in bars], "realized_volatility": realized_volatility([b.close for b in bars]), "source": "alpaca", "feed": os.getenv("ALPACA_STOCK_FEED", "iex"), "last_ingestion": {"status": run.status, "message": run.message, "started_at": run.started_at} if run else None}

@router.get("/securities/{ticker}/snapshot")
async def stock_snapshot(ticker: str):
    with Session() as db:
        ticker = get_security(db, ticker).ticker
    if selected_provider() != "alpaca":
        raise HTTPException(501, "Stock snapshots are not supported by the selected provider.")
    try:
        return {"source": "alpaca", "feed": os.getenv("ALPACA_STOCK_FEED", "iex"), "snapshot": await AlpacaProvider().stock_snapshot(ticker)}
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc

@router.get("/securities/{ticker}/options")
def market_options(ticker: str):
    if selected_provider() == "alphavantage":
        from .main import options
        return options(ticker)
    with Session() as db:
        sec = get_security(db, ticker)
        rows = db.execute(select(Contract, MarketOptionQuote).join(MarketOptionQuote).where(Contract.security_id == sec.id, MarketOptionQuote.source == "alpaca", MarketOptionQuote.feed == os.getenv("ALPACA_OPTIONS_FEED", "indicative")).order_by(MarketOptionQuote.retrieved_at.desc(), MarketOptionQuote.id.desc())).all()
        latest = {}
        for contract, quote in rows:
            if contract.symbol not in latest:
                latest[contract.symbol] = serialize_quote(contract, quote)
        return sorted(latest.values(), key=lambda row: (row["expiration"], row["strike"], row["kind"]))

@router.get("/scan")
def market_scan(max_spread: float = Query(default=1.0, ge=0), min_open_interest: int = Query(default=0, ge=0), include_stale: bool = False):
    if selected_provider() == "alphavantage":
        from .main import scan
        return scan()
    from .main import UNIVERSE
    results = []
    today = date.today()
    for ticker in UNIVERSE:
        info = market_detail(ticker)
        rv = info["realized_volatility"]
        if rv is None:
            continue
        for row in market_options(ticker):
            days = (row["expiration"] - today).days
            if not 90 <= days <= 548 or row["iv"] is None or row["iv"] <= 0 or row["spread"] is None or row["spread"] > max_spread or (row["stale"] and not include_stale):
                continue
            if min_open_interest and (row["open_interest"] is None or row["open_interest"] < min_open_interest):
                continue
            row.update({"ticker": ticker, "realized_volatility": rv, "iv_minus_rv": row["iv"] - rv, "break_even": row["strike"] + row["ask"] if row["kind"] == "call" else row["strike"] - row["ask"], "maximum_loss": row["ask"] * 100})
            row["screen_factors"] = screen_factors(row, rv)
            results.append(row)
    return sorted(results, key=lambda row: (row["screen_factors"]["score"] is None, -(row["screen_factors"]["score"] or 0)))

@router.post("/securities/{ticker}/options/{symbol}/verify")
async def verify(ticker: str, symbol: str, historical_date: date | None = None):
    if os.getenv("ENABLE_SECONDARY_VERIFICATION", "true").lower() != "true":
        raise HTTPException(403, "Secondary verification is disabled.")
    if os.getenv("SECONDARY_MARKET_DATA_PROVIDER", "marketdata").lower() != "marketdata":
        raise HTTPException(503, "Unsupported secondary provider.")
    primary = next((q for q in market_options(ticker) if q["symbol"] == symbol), None)
    if primary is None:
        raise HTTPException(404, "No primary quote for this contract.")
    try:
        secondary = await MarketDataProvider().quote(symbol, historical_date) if historical_date else await MarketDataProvider().quote(symbol)
        if secondary.underlying != ticker.upper():
            raise ValueError("Contract underlying does not match.")
        with Session.begin() as db:
            sec = get_security(db, ticker)
            persist_quote(db, sec, secondary)
            db.flush()
            contract = db.scalar(select(Contract).where(Contract.symbol == symbol))
            fields = secondary.model_dump(exclude={"symbol", "underlying", "expiration", "kind", "strike"})
            # Compare the response just fetched, even when it was already stored.
            result = serialize_quote(contract, MarketOptionQuote(contract_id=contract.id, **fields))
        return compare(primary, result)
    except (ProviderError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from .analytics import payoff

class Scenario(BaseModel):
    price: float = Field(ge=0)
    probability: float = Field(ge=0, le=1)

class ScenarioRequest(BaseModel):
    kind: Literal["call", "put"]
    strike: float = Field(gt=0)
    premium: float = Field(ge=0)
    transaction_cost: float = Field(default=0, ge=0)
    scenarios: list[Scenario] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def probabilities_sum_to_one(self):
        if abs(sum(s.probability for s in self.scenarios) - 1) > 1e-6:
            raise ValueError("Scenario probabilities must sum to one.")
        return self

@router.post("/scenarios/expiration")
def expiration_scenarios(request: ScenarioRequest):
    outcomes = [{"price": s.price, "probability": s.probability, "net_profit": payoff(request.kind, request.strike, request.premium, s.price) - request.transaction_cost} for s in request.scenarios]
    return {"outcomes": outcomes, "expected_value": sum(s["net_profit"] * s["probability"] for s in outcomes), "note": "Hypothetical expiration scenarios; probabilities are user assumptions. Excludes early exercise."}

@router.get("/securities/{ticker}/options/{symbol}/trades")
async def option_trades(ticker: str, symbol: str, start: datetime, end: datetime):
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > timedelta(days=31):
        raise HTTPException(422, "Supply timezone-aware start and end, at most 31 days apart.")
    with Session() as db:
        sec = get_security(db, ticker)
        contract = db.scalar(select(Contract).where(Contract.symbol == symbol, Contract.security_id == sec.id))
        if not contract:
            raise HTTPException(404, "Contract not found.")
    try:
        return {"source": "alpaca", "feed": "provider historical entitlement", "trades": await AlpacaProvider().historical_trades(symbol, start, end), "limit": 1000}
    except (ProviderError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
