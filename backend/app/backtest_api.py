"""Backtest readiness gate. No synthetic backtest results are exposed."""
from datetime import date, timedelta
import os
from typing import Literal
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from .db import Session
from .market_db import MarketOptionQuote
from .optionsdx_research import ResearchDataError, open_data, quality_report, research_replay, estimated_european_iv

router = APIRouter(prefix="/backtests", tags=["backtesting"])

class BacktestRequest(BaseModel):
    start: date
    out_of_sample_start: date
    end: date
    benchmark: str = Field(default="SPY", min_length=1, max_length=12)
    transaction_cost: float = Field(ge=0, le=10000)

    @model_validator(mode="after")
    def chronological(self):
        if not self.start < self.out_of_sample_start <= self.end:
            raise ValueError("Require start < out_of_sample_start <= end.")
        return self

class ExploratoryRequest(BaseModel):
    ticker: Literal['AAPL', 'NVDA', 'TSLA'] = 'AAPL'
    start: date
    end: date
    transaction_cost: float = Field(ge=0, le=10000, allow_inf_nan=False)

@router.get("/optionsdx/quality")
def optionsdx_quality(ticker: Literal['AAPL', 'NVDA', 'TSLA'] = 'AAPL'):
    try:
        with open_data() as db:
            return quality_report(db, ticker)
    except (ResearchDataError, OSError) as exc:
        raise HTTPException(409, detail=str(exc)) from exc

@router.post("/optionsdx/exploratory")
def optionsdx_exploratory(request: ExploratoryRequest):
    try:
        with open_data() as db:
            return research_replay(db, request.ticker, request.start, request.end, request.transaction_cost)
    except (ResearchDataError, OSError) as exc:
        raise HTTPException(409, detail=str(exc)) from exc

@router.get("/optionsdx/iv-comparison")
def optionsdx_iv_comparison(rate: float = .05, dividend_yield: float = .005):
    if not (-.1 <= rate <= .3 and 0 <= dividend_yield <= .3):
        raise HTTPException(422, detail="Rate or dividend assumption is outside the supported range.")
    try:
        with open_data() as db:
            quality_report(db, "AAPL")
            rows = db.execute("""SELECT * FROM option_observations WHERE ticker='AAPL'
                AND implied_volatility > 0 AND bid > 0 AND ask >= bid AND underlying_price > 0
                AND julianday(expiration)-julianday(quote_date) BETWEEN 90 AND 548
                AND strike_millis / 1000.0 BETWEEN underlying_price * .9 AND underlying_price * 1.1
                AND (ask-bid)/((ask+bid)/2) <= .2 ORDER BY quote_date, expiration, strike_millis, kind LIMIT 200""").fetchall()
            differences = []
            for row in rows:
                years = (date.fromisoformat(row['expiration']) - date.fromisoformat(row['quote_date'])).days / 365
                estimate = estimated_european_iv(row['kind'], row['underlying_price'], row['strike_millis']/1000,
                    years, row['bid'], row['ask'], rate, dividend_yield)
                if estimate is not None:
                    differences.append(abs(estimate - row['implied_volatility']))
            missing_rows = db.execute("""SELECT * FROM option_observations WHERE ticker='AAPL'
                AND (implied_volatility IS NULL OR implied_volatility<=0) AND bid>0 AND ask>=bid AND underlying_price>0
                AND julianday(expiration)-julianday(quote_date) BETWEEN 90 AND 548
                AND (ask-bid)/((ask+bid)/2)<=.2 ORDER BY quote_date, expiration, strike_millis, kind LIMIT 200""").fetchall()
            reconstructed = []
            for row in missing_rows:
                years = (date.fromisoformat(row['expiration']) - date.fromisoformat(row['quote_date'])).days / 365
                estimate = estimated_european_iv(row['kind'], row['underlying_price'], row['strike_millis']/1000,
                    years, row['bid'], row['ask'], rate, dividend_yield)
                if estimate is not None:
                    reconstructed.append({'date':row['quote_date'], 'expiration':row['expiration'], 'strike':row['strike_millis']/1000,
                        'kind':row['kind'], 'estimated_iv':estimate, 'source':'European midpoint model, illustrative assumptions'})
            return {'sample_rows':len(rows), 'estimated_rows':len(differences),
                'mean_absolute_difference':sum(differences)/len(differences) if differences else None,
                'missing_sample_rows':len(missing_rows), 'missing_estimable':len(reconstructed), 'estimate_examples':reconstructed[:5],
                'risk_free_rate_assumption':rate, 'dividend_yield_assumption':dividend_yield,
                'note':'Illustrative European-model estimates for American-style options; fixed rate and dividend assumptions are not verified historical inputs. Sample is the first 200 qualifying rows, not representative. Estimates are not used in the replay.'}
    except (ResearchDataError, OSError) as exc:
        raise HTTPException(409, detail=str(exc)) from exc

@router.get("/readiness")
def readiness():
    with Session() as db:
        count, earliest, latest = db.execute(select(func.count(MarketOptionQuote.id), func.min(MarketOptionQuote.quote_timestamp), func.max(MarketOptionQuote.quote_timestamp))).one()
        feeds = db.execute(select(MarketOptionQuote.source, MarketOptionQuote.feed, func.count()).group_by(MarketOptionQuote.source, MarketOptionQuote.feed)).all()
    return {"status": "incomplete", "saved_quote_count": count, "earliest_quote": earliest, "latest_quote": latest,
        "feeds": [{"source": source, "feed": feed, "count": amount} for source, feed, amount in feeds],
        "blockers": [
            "MarketData historical chains do not include implied volatility, which the current signal requires.",
            "No verified point-in-time historical option quote dataset with executable bid/ask and liquidity coverage is configured.",
            "No historical survivorship-aware security universe is configured.",
            "Point-in-time corporate actions, benchmark total returns and data-availability timestamps have not been validated.",
            "Signal replay, expiration handling and out-of-sample execution integration are not complete."
        ], "note": "Saved snapshots and indicative quotes do not establish historical coverage or executable prices."}

@router.post("/coverage-check")
async def coverage_check():
    """One tightly filtered sample, not a claim of full historical coverage."""
    token = os.getenv("MARKETDATA_API_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="MarketData token is not configured.")
    day = date.today() - timedelta(days=120)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://api.marketdata.app/v1/options/chain/AAPL/",
                headers={"Authorization": f"Bearer {token}"},
                params={"date": day.isoformat(), "dte": "120", "side": "call", "strikeLimit": "1"})
        if response.status_code not in (200, 203):
            raise HTTPException(status_code=502, detail=f"MarketData coverage check failed (HTTP {response.status_code}). Check account access or credits.")
        data = response.json()
        if data.get("s") != "ok" or not isinstance(data.get("optionSymbol"), list) or not data["optionSymbol"]:
            raise HTTPException(status_code=502, detail="MarketData returned no sample for this date. This does not establish overall coverage.")
        def present(field):
            values = data.get(field)
            return isinstance(values, list) and bool(values) and values[0] is not None
        return {"sample_date": day, "ticker": "AAPL", "contract_count": len(data["optionSymbol"]),
            "fields": {field: present(field) for field in ("bid", "ask", "bidSize", "askSize", "iv", "volume", "openInterest", "updated")},
            "credits_consumed": response.headers.get("x-api-ratelimit-consumed"),
            "credits_remaining": response.headers.get("x-api-ratelimit-remaining"),
            "note": "One historical sample does not establish coverage, quote executability, or signal availability across the test period."}
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=502, detail="MarketData coverage check could not be completed.")

@router.post("")
def run_backtest(request: BacktestRequest):
    # Fail closed: no fabricated data and no apparent performance result.
    raise HTTPException(status_code=409, detail={"status": "incomplete", "message": "Backtest cannot run until the readiness blockers are resolved.", "blockers": readiness()["blockers"]})
