import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from .analytics import payoff, realized_volatility, spread
from .ranking import screen_factors
from .db import Base, Contract, IngestionRun, Price, Quote, Security, Session, engine
from .provider import AlphaVantage, ProviderError
from . import market_db
from .market_api import router as market_router
from .research_api import router as research_router
from .watchlist_api import router as watchlist_router
from .paper_api import router as paper_router
from .backtest_api import router as backtest_router

UNIVERSE = ("AAPL", "MSFT", "NVDA", "SPY", "TSLA")

@asynccontextmanager
async def lifespan(app: FastAPI):
    with Session.begin() as db:
        for ticker in UNIVERSE:
            if not db.scalar(select(Security).where(Security.ticker == ticker)):
                db.add(Security(ticker=ticker))
    yield

app = FastAPI(title="Asymmetry Research API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","), allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

class PayoffRequest(BaseModel):
    kind: Literal["call", "put"]
    strike: float = Field(gt=0)
    premium: float = Field(ge=0)
    price: float = Field(ge=0)
    contracts: int = Field(default=1, ge=1, le=10000)

class PayoffResponse(BaseModel):
    net_profit: float
    break_even: float
    max_loss: float
    note: str

def number(value):
    try:
        return float(value) if value not in (None, "", "None") else None
    except (ValueError, TypeError):
        return None

def security(db, ticker):
    item = db.scalar(select(Security).where(Security.ticker == ticker.upper()))
    if not item:
        raise HTTPException(404, "Ticker is outside the configured universe.")
    return item

@app.get("/health")
def health():
    return {"status": "ok", "provider": os.getenv("PRIMARY_MARKET_DATA_PROVIDER", "alpaca"), "provider_configured": bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY")) if os.getenv("PRIMARY_MARKET_DATA_PROVIDER", "alpaca") == "alpaca" else bool(os.getenv("ALPHA_VANTAGE_API_KEY")), "universe": UNIVERSE}

@app.get("/securities")
def securities():
    with Session() as db:
        return [{"ticker": s.ticker} for s in db.scalars(select(Security).order_by(Security.ticker))]


async def ingest(ticker: str):
    with Session() as db:
        sec = security(db, ticker)
        ticker = sec.ticker
    provider = AlphaVantage()
    try:
        prices = await provider.prices(ticker)
        options = await provider.options(ticker)
        series = prices.get("Time Series (Daily)")
        rows = options.get("data")
        if not isinstance(series, dict) or not isinstance(rows, list) or not rows:
            raise ProviderError("Provider returned incomplete prices or options data.")
        with Session.begin() as db:
            sec = security(db, ticker)
            for day, row in series.items():
                d = date.fromisoformat(day)
                close = number(row.get("4. close"))
                if close is not None and close > 0 and not db.scalar(select(Price).where(Price.security_id == sec.id, Price.date == d, Price.source == "Alpha Vantage")):
                    db.add(Price(security_id=sec.id, date=d, close=close, source="Alpha Vantage"))
            count = 0
            for row in rows:
                try:
                    symbol = row["contractID"]
                    expiry = date.fromisoformat(row["expiration"])
                    observed = date.fromisoformat(row["date"])
                    kind = row["type"].lower()
                    strike = float(row["strike"])
                    if kind not in ("call", "put") or strike <= 0:
                        continue
                except (KeyError, ValueError, TypeError):
                    continue
                contract = db.scalar(select(Contract).where(Contract.symbol == symbol))
                if contract is None:
                    contract = Contract(security_id=sec.id, symbol=symbol, expiration=expiry, kind=kind, strike=strike)
                    db.add(contract)
                    db.flush()
                if not db.scalar(select(Quote).where(Quote.contract_id == contract.id, Quote.date == observed, Quote.source == "Alpha Vantage")):
                    db.add(Quote(contract_id=contract.id, date=observed, bid=number(row.get("bid")), ask=number(row.get("ask")), iv=number(row.get("implied_volatility")), volume=int(number(row.get("volume"))) if number(row.get("volume")) is not None else None, open_interest=int(number(row.get("open_interest"))) if number(row.get("open_interest")) is not None else None, source="Alpha Vantage"))
                    count += 1
            db.add(IngestionRun(ticker=ticker, status="success", message=f"Saved {count} new option observations"))
        return {"ticker": ticker, "new_option_quotes": count}
    except (ProviderError, ValueError) as exc:
        with Session.begin() as db:
            db.add(IngestionRun(ticker=ticker, status="error", message=str(exc)[:500]))
        raise HTTPException(503, str(exc)) from exc


def detail(ticker: str):
    with Session() as db:
        sec = security(db, ticker)
        prices = list(db.scalars(select(Price).where(Price.security_id == sec.id).order_by(Price.date)))
        runs = list(db.scalars(select(IngestionRun).where(IngestionRun.ticker == sec.ticker).order_by(IngestionRun.id.desc()).limit(1)))
        rv = realized_volatility([p.close for p in prices])
        return {"ticker": sec.ticker, "prices": [{"date": p.date, "close": p.close} for p in prices], "realized_volatility": rv, "source": "Alpha Vantage", "last_ingestion": {"status": runs[0].status, "message": runs[0].message, "started_at": runs[0].started_at} if runs else None}


def options(ticker: str):
    with Session() as db:
        sec = security(db, ticker)
        latest = db.scalar(select(Quote.date).join(Contract).where(Contract.security_id == sec.id).order_by(Quote.date.desc()).limit(1))
        if not latest:
            return []
        rows = db.execute(select(Contract, Quote).join(Quote).where(Contract.security_id == sec.id, Quote.date == latest).order_by(Contract.expiration, Contract.strike)).all()
        return [{"symbol": c.symbol, "expiration": c.expiration, "kind": c.kind, "strike": c.strike, "date": q.date, "bid": q.bid, "ask": q.ask, "iv": q.iv, "volume": q.volume, "open_interest": q.open_interest, "spread": spread(q.bid, q.ask), "source": q.source} for c, q in rows]


def scan():
    results = []
    for ticker in UNIVERSE:
        info = detail(ticker)
        rv = info["realized_volatility"]
        if rv is None:
            continue
        for row in options(ticker):
            if row["iv"] is None or row["iv"] <= 0 or row["spread"] is None or row["expiration"] < date.today():
                continue
            result = {"ticker": ticker, "realized_volatility": rv, "iv_minus_rv": row["iv"] - rv, "stale": True, "quote_timestamp": None, **row}
            result["screen_factors"] = screen_factors(result, rv)
            results.append(result)
    return sorted(results, key=lambda row: (row["screen_factors"]["score"] is None, -(row["screen_factors"]["score"] or 0)))

@app.post("/payoff", response_model=PayoffResponse)
def calculate(request: PayoffRequest):
    return PayoffResponse(net_profit=payoff(request.kind, request.strike, request.premium, request.price, request.contracts), break_even=request.strike + request.premium if request.kind == "call" else request.strike - request.premium, max_loss=request.premium * 100 * request.contracts, note="Hypothetical expiration payoff; excludes fees, exercise costs and early exercise.")


app.include_router(market_router)

app.include_router(research_router)

app.include_router(watchlist_router)

app.include_router(paper_router)

app.include_router(backtest_router)
