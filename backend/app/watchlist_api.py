from datetime import date, datetime, timedelta, timezone
from typing import Literal
import os
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from .analytics import payoff, european_option_value
from .db import Contract, Security, Session
from .market_db import MarketBar, MarketOptionQuote
from .market_service import aware, serialize_quote
from .watchlist_db import ResearchAssessment, ScenarioSnapshot, WatchlistItem
from .research_db import SourceDocument
from .analytics import realized_volatility
from .ranking import screen_factors, watchlist_priority

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

class AddItem(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    symbol: str = Field(min_length=1, max_length=80)

class UserScenario(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=40)
    price: float = Field(ge=0, le=1_000_000)
    probability: float = Field(ge=0, le=1)
    volatility: float | None = Field(default=None, ge=0, le=5)

class Assumptions(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    premium: float = Field(gt=0, le=1_000_000)
    transaction_cost: float = Field(ge=0, le=1_000_000)
    valuation_date: date | None = None
    risk_free_rate: float | None = Field(default=None, ge=-0.2, le=1)
    dividend_yield: float | None = Field(default=None, ge=0, le=1)
    scenarios: list[UserScenario] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def validate_probabilities(self):
        if abs(sum(s.probability for s in self.scenarios) - 1) > 0.000001:
            raise ValueError("Scenario probabilities must sum to 100%.")
        return self

class AssessmentRequest(BaseModel):
    catalyst_relevance: Literal["unknown", "low", "medium", "high"]
    evidence_quality: Literal["unknown", "weak", "mixed", "strong"]
    notes: str = Field(default="", max_length=2000)
    source_ids: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_evidence(self):
        if (self.catalyst_relevance != "unknown" or self.evidence_quality != "unknown") and not self.source_ids:
            raise ValueError("Select at least one source for a research assessment.")
        return self

def get_item(db, item_id):
    item = db.get(WatchlistItem, item_id)
    if not item or item.archived:
        raise HTTPException(404, "Watchlist item not found.")
    contract = db.get(Contract, item.contract_id)
    security = db.get(Security, contract.security_id)
    return item, contract, security

def latest_quote(db, contract):
    # Do not silently substitute another source or feed.
    if os.getenv("PRIMARY_MARKET_DATA_PROVIDER", "alpaca").lower() != "alpaca":
        return None
    quote = db.scalar(select(MarketOptionQuote).where(
        MarketOptionQuote.contract_id == contract.id,
        MarketOptionQuote.source == "alpaca",
        MarketOptionQuote.feed == os.getenv("ALPACA_OPTIONS_FEED", "indicative")
    ).order_by(MarketOptionQuote.retrieved_at.desc(), MarketOptionQuote.id.desc()).limit(1))
    return serialize_quote(contract, quote) if quote else None

def item_json(db, item, contract, security):
    quote = latest_quote(db, contract)
    assessment = db.scalar(select(ResearchAssessment).where(ResearchAssessment.watchlist_item_id == item.id).order_by(ResearchAssessment.id.desc()).limit(1))
    scenario = db.scalar(select(ScenarioSnapshot).where(ScenarioSnapshot.watchlist_item_id == item.id).order_by(ScenarioSnapshot.id.desc()).limit(1))
    bars = list(db.scalars(select(MarketBar).where(MarketBar.security_id == security.id, MarketBar.source == "alpaca",
        MarketBar.feed == os.getenv("ALPACA_STOCK_FEED", "iex")).order_by(MarketBar.timestamp.desc()).limit(21)))
    rv = realized_volatility([bar.close for bar in reversed(bars)]) if bars else None
    latest_bar_time = aware(bars[0].timestamp) if bars else None
    now = datetime.now(timezone.utc)
    bars_fresh = bool(latest_bar_time and now - timedelta(days=7) <= latest_bar_time <= now + timedelta(minutes=5))
    quant = screen_factors(quote, rv) if quote and rv is not None else None
    values = assessment.inputs if assessment else {}
    assumptions = scenario.assumptions if scenario else {}
    capital = (assumptions.get("premium", 0) * 100 + assumptions.get("transaction_cost", 0)) if scenario else None
    valuation_date = assumptions.get("valuation_date")
    scenario_current = scenario is not None and (not valuation_date or date.fromisoformat(valuation_date) >= date.today()) and contract.expiration >= date.today()
    priority = watchlist_priority(quant["score"] if quant else None,
        scenario.results.get("expected_value") if scenario_current else None,
        capital, values.get("catalyst_relevance", "unknown"), values.get("evidence_quality", "unknown"),
        fresh=bool(quote and not quote["stale"] and bars_fresh))
    priority.update({"latest_bar_time": latest_bar_time, "bars_fresh": bars_fresh, "scenario_id": scenario.id if scenario else None, "scenario_created_at": scenario.created_at if scenario else None,
                     "scenario_current": scenario_current, "assessment_id": assessment.id if assessment else None,
                     "assessment_created_at": assessment.created_at if assessment else None})
    return {"id": item.id, "ticker": security.ticker, "symbol": contract.symbol, "kind": contract.kind,
        "strike": contract.strike, "expiration": contract.expiration, "created_at": item.created_at,
        "current_quote": quote, "research_assessment": values if assessment else None, "priority": priority}

def scenario_result(contract, request: Assumptions):
    if request.valuation_date is not None and request.valuation_date < date(2000, 1, 1):
        raise HTTPException(422, "The valuation date must be in or after 2000.")
    if request.valuation_date is not None and request.valuation_date > contract.expiration:
        raise HTTPException(422, "The valuation date cannot be after expiration.")
    before_expiry = request.valuation_date is not None and request.valuation_date < contract.expiration
    if before_expiry and (request.risk_free_rate is None or request.dividend_yield is None or any(s.volatility is None for s in request.scenarios)):
        raise HTTPException(422, "Pre-expiration scenarios require a volatility for each outcome, a rate, and a dividend yield.")
    years = (contract.expiration - request.valuation_date).days / 365 if before_expiry else 0
    outcomes = []
    for scenario in request.scenarios:
        option_value = european_option_value(contract.kind, scenario.price, contract.strike, years, scenario.volatility, request.risk_free_rate, request.dividend_yield) if before_expiry else max(scenario.price - contract.strike, 0) if contract.kind == "call" else max(contract.strike - scenario.price, 0)
        gross = (option_value - request.premium) * 100
        profit = gross - request.transaction_cost
        outcomes.append({"name": scenario.name, "price": scenario.price, "probability": scenario.probability, "volatility": scenario.volatility, "option_value": option_value, "gross_profit": gross, "net_profit": profit, "return_on_capital": profit / (request.premium * 100 + request.transaction_cost)})
    expected = sum(s["probability"] * s["net_profit"] for s in outcomes)
    break_even_probability = None
    if len(outcomes) == 2:
        gains = [s["net_profit"] for s in outcomes if s["net_profit"] > 0]
        losses = [s["net_profit"] for s in outcomes if s["net_profit"] < 0]
        if len(gains) == len(losses) == 1:
            break_even_probability = -losses[0] / (gains[0] - losses[0])
    return {"outcomes": outcomes, "expected_value": expected, "break_even_probability": break_even_probability,
        "valuation_date": str(request.valuation_date or contract.expiration),
        "model": "European Black-Scholes-Merton" if before_expiry else "expiration intrinsic value",
        "note": "Hypothetical values, not executable quotes. Black-Scholes assumes European exercise, constant volatility and continuous dividend yield; US equity options are generally American-style, and discrete dividends and early exercise are not modeled. Excludes tax." if before_expiry else "Hypothetical expiration outcomes; probabilities are user assumptions. One standard long contract; excludes early exercise and tax."}

@router.get("")
def list_items():
    with Session() as db:
        rows = db.execute(select(WatchlistItem, Contract, Security).join(Contract, WatchlistItem.contract_id == Contract.id).join(Security, Contract.security_id == Security.id).where(WatchlistItem.archived == False).order_by(WatchlistItem.id.desc())).all()  # noqa: E712
        items = [item_json(db, item, contract, sec) for item, contract, sec in rows]
        return sorted(items, key=lambda item: (item["priority"]["score"] is None, -(item["priority"]["score"] or 0)))

@router.post("", status_code=201)
def add_item(request: AddItem):
    with Session.begin() as db:
        row = db.execute(select(Contract, Security).join(Security).where(Security.ticker == request.ticker.upper(), Contract.symbol == request.symbol)).first()
        if not row:
            raise HTTPException(404, "Option contract not found for this ticker.")
        contract, sec = row
        item = db.scalar(select(WatchlistItem).where(WatchlistItem.contract_id == contract.id))
        if item:
            item.archived = False
        else:
            item = WatchlistItem(contract_id=contract.id, archived=False)
            db.add(item)
            db.flush()
        return item_json(db, item, contract, sec)

@router.delete("/{item_id}", status_code=204)
def archive_item(item_id: int):
    with Session.begin() as db:
        item, _, _ = get_item(db, item_id)
        item.archived = True

@router.get("/{item_id}/quotes")
def quote_history(item_id: int, source: Literal["alpaca", "marketdata"] = "alpaca", feed: str | None = Query(default=None, max_length=40), offset: int = Query(default=0, ge=0, le=100000)):
    with Session() as db:
        _, contract, _ = get_item(db, item_id)
        query = select(MarketOptionQuote).where(MarketOptionQuote.contract_id == contract.id, MarketOptionQuote.source == source)
        if feed is not None:
            query = query.where(MarketOptionQuote.feed == feed)
        quotes = db.scalars(query.order_by(MarketOptionQuote.retrieved_at.desc(), MarketOptionQuote.id.desc()).offset(offset).limit(100))
        return [serialize_quote(contract, quote) for quote in quotes]

@router.post("/{item_id}/calculate")
def calculate(item_id: int, request: Assumptions):
    with Session() as db:
        _, contract, _ = get_item(db, item_id)
        return scenario_result(contract, request)

@router.post("/{item_id}/scenarios", status_code=201)
def save_scenario(item_id: int, request: Assumptions):
    with Session.begin() as db:
        item, contract, _ = get_item(db, item_id)
        result = scenario_result(contract, request)
        quote = latest_quote(db, contract)
        snapshot = ScenarioSnapshot(watchlist_item_id=item.id, assumptions=request.model_dump(), results=result, quote_snapshot=jsonable_encoder(quote) if quote else None)
        db.add(snapshot)
        db.flush()
        return {"id": snapshot.id, "created_at": snapshot.created_at, "assumptions": snapshot.assumptions, "results": snapshot.results, "quote_snapshot": snapshot.quote_snapshot}

@router.get("/{item_id}/scenarios")
def scenario_history(item_id: int):
    with Session() as db:
        item, _, _ = get_item(db, item_id)
        snapshots = db.scalars(select(ScenarioSnapshot).where(ScenarioSnapshot.watchlist_item_id == item.id).order_by(ScenarioSnapshot.id.desc()).limit(50))
        return [{"id": s.id, "created_at": s.created_at, "assumptions": s.assumptions, "results": s.results, "quote_snapshot": s.quote_snapshot} for s in snapshots]


@router.post("/{item_id}/assessments", status_code=201)
def save_assessment(item_id: int, request: AssessmentRequest):
    with Session.begin() as db:
        item, _, sec = get_item(db, item_id)
        ids = list(dict.fromkeys(request.source_ids))
        found = list(db.scalars(select(SourceDocument.id).where(SourceDocument.security_id == sec.id, SourceDocument.id.in_(ids))))
        if len(found) != len(ids):
            raise HTTPException(422, "All sources must exist and belong to this ticker.")
        values = request.model_dump()
        values["source_ids"] = ids
        assessment = ResearchAssessment(watchlist_item_id=item.id, inputs=values)
        db.add(assessment)
        db.flush()
        return {"id": assessment.id, "created_at": assessment.created_at, "inputs": assessment.inputs}

@router.get("/{item_id}/assessments")
def assessment_history(item_id: int):
    with Session() as db:
        item, _, _ = get_item(db, item_id)
        records = db.scalars(select(ResearchAssessment).where(ResearchAssessment.watchlist_item_id == item.id).order_by(ResearchAssessment.id.desc()).limit(50))
        return [{"id": row.id, "created_at": row.created_at, "inputs": row.inputs} for row in records]
