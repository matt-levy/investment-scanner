import hashlib
import json
import os
from datetime import datetime, timezone
from sqlalchemy import select
from .db import Contract, Security
from .market_db import MarketBar, MarketOptionQuote
from .market_models import OptionObservation
from .analytics import spread

def aware(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def persist_bar(db, security: Security, bar):
    existing = db.scalar(select(MarketBar).where(MarketBar.security_id == security.id, MarketBar.timestamp == bar.timestamp, MarketBar.source == bar.source, MarketBar.feed == bar.feed))
    if not existing:
        db.add(MarketBar(security_id=security.id, **bar.model_dump(exclude={"symbol"})))

def persist_quote(db, security: Security, obs: OptionObservation):
    contract = db.scalar(select(Contract).where(Contract.symbol == obs.symbol))
    if not contract:
        contract = Contract(security_id=security.id, symbol=obs.symbol, expiration=obs.expiration, kind=obs.kind, strike=obs.strike)
        db.add(contract)
        db.flush()
    elif contract.security_id != security.id or contract.expiration != obs.expiration or contract.kind != obs.kind or contract.strike != obs.strike:
        raise ValueError("Conflicting option contract identity")
    fields = obs.model_dump(exclude={"symbol", "underlying", "expiration", "kind", "strike", "retrieved_at"})
    key = hashlib.sha256(json.dumps(fields, default=str, sort_keys=True).encode()).hexdigest()
    existing = db.scalar(select(MarketOptionQuote).where(MarketOptionQuote.contract_id == contract.id, MarketOptionQuote.source == obs.source, MarketOptionQuote.feed == obs.feed, MarketOptionQuote.observation_key == key))
    if existing:
        return False
    db.add(MarketOptionQuote(contract_id=contract.id, observation_key=key, retrieved_at=obs.retrieved_at, **fields))
    return True

def serialize_quote(contract, quote):
    timestamp = aware(quote.quote_timestamp)
    age = (datetime.now(timezone.utc) - timestamp).total_seconds() if timestamp else None
    stale = age is None or age > int(os.getenv("QUOTE_STALE_SECONDS", "900")) or age < -60
    warnings = []
    if quote.feed == "indicative":
        warnings.append("Indicative feed: not executable.")
    if stale:
        warnings.append("Quote is stale or its timestamp is unavailable.")
    if quote.bid is None or quote.ask is None or quote.iv is None:
        warnings.append("Bid, ask, or implied volatility is missing.")
    return {"symbol": contract.symbol, "expiration": contract.expiration, "kind": contract.kind, "strike": contract.strike,
        "date": timestamp.date() if timestamp else None, "quote_timestamp": timestamp, "retrieved_at": aware(quote.retrieved_at),
        "bid": quote.bid, "ask": quote.ask, "bid_exchange": quote.bid_exchange, "ask_exchange": quote.ask_exchange, "bid_size": quote.bid_size, "ask_size": quote.ask_size,
        "iv": quote.iv, "delta": quote.delta, "gamma": quote.gamma, "theta": quote.theta, "vega": quote.vega, "rho": quote.rho,
        "volume": quote.volume, "open_interest": quote.open_interest, "spread": spread(quote.bid, quote.ask),
        "source": quote.source, "feed": quote.feed, "classification": quote.classification, "stale": stale,
        "warning": " ".join(warnings) or None}

def compare(primary: dict, secondary: dict) -> dict:
    a, b = aware(primary.get("quote_timestamp")), aware(secondary.get("quote_timestamp"))
    skew = abs((a - b).total_seconds()) if a and b else None
    warnings = []
    if skew is None:
        warnings.append("At least one quote timestamp is missing; prices cannot be compared as simultaneous.")
    elif skew > 300:
        warnings.append("Quotes are more than five minutes apart; differences may reflect market movement or delayed data.")
    if primary.get("stale") or secondary.get("stale"):
        warnings.append("At least one observation is stale or has an unknown timestamp.")
    if primary.get("feed") == "indicative":
        warnings.append("Alpaca indicative prices are not executable.")
    if any(primary.get(k) is None or secondary.get(k) is None for k in ("bid", "ask", "iv")):
        warnings.append("Bid, ask or implied volatility is missing.")
    changes = {}
    for field in ("bid", "ask", "iv"):
        x, y = primary.get(field), secondary.get(field)
        changes[field] = y - x if x is not None and y is not None else None
    def midpoint(q):
        return (q["bid"] + q["ask"]) / 2 if q.get("bid") is not None and q.get("ask") is not None else None
    x, y = midpoint(primary), midpoint(secondary)
    changes["midpoint"] = y - x if x is not None and y is not None else None
    significant = (x is not None and y is not None and x > 0 and abs(y-x)/x > .1) or (changes["iv"] is not None and abs(changes["iv"]) > .05)
    if significant:
        warnings.append("Large difference: investigate feed differences, timing, stale prices and liquidity.")
    return {"primary": primary, "secondary": secondary, "timestamp_difference_seconds": skew, "differences_secondary_minus_primary": changes, "significant_discrepancy": significant, "warnings": warnings}
