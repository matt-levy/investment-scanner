from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import asyncio
import pytest
from sqlalchemy import select
from app.db import Base, Security, Session, engine
from app.market_db import MarketBar, MarketOptionQuote
from app.market_models import OptionObservation
from app.market_providers import AlpacaProvider, MarketDataProvider, normalize_alpaca, parse_occ
from app.market_service import compare, persist_quote, serialize_quote
from app.provider import ProviderError

def test_occ_and_normalization():
    assert parse_occ("AAPL271217C00250000") == ("AAPL", date(2027, 12, 17), "call", 250.0)
    with pytest.raises(ValueError):
        parse_occ("bad")
    now = datetime.now(timezone.utc)
    quote = SimpleNamespace(timestamp=now, bid_price=1.0, ask_price=1.2, bid_size=5, ask_size=8, bid_exchange=None, ask_exchange=None)
    snapshot = SimpleNamespace(latest_quote=quote, greeks=SimpleNamespace(delta=.5, gamma=.1, theta=-.02, vega=.2), implied_volatility=.3)
    result = normalize_alpaca("AAPL271217C00250000", "AAPL", snapshot, "indicative", now)
    assert result.bid == 1 and result.delta == .5 and result.open_interest is None
    assert result.feed == "indicative"

def test_persistence_dedup_and_freshness():
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session.begin() as db:
        sec = db.scalar(select(Security).where(Security.ticker == "AAPL"))
        if sec is None:
            sec = Security(ticker="AAPL")
            db.add(sec)
            db.flush()
        obs = OptionObservation(symbol="AAPL271217C00250000", underlying="AAPL", expiration=date(2027,12,17), kind="call", strike=250, source="test", feed="indicative", quote_timestamp=now-timedelta(days=1), retrieved_at=now, bid=1, ask=2)
        assert persist_quote(db, sec, obs)
        db.flush()
        assert not persist_quote(db, sec, obs)
        newer = obs.model_copy(update={"quote_timestamp": now, "retrieved_at": now})
        assert persist_quote(db, sec, newer)
        db.flush()
        quotes = list(db.scalars(select(MarketOptionQuote).where(MarketOptionQuote.source == "test").order_by(MarketOptionQuote.id)))
        assert len(quotes) == 2
        assert serialize_quote(db.get(__import__("app.db", fromlist=["Contract"]).Contract, quotes[0].contract_id), quotes[0])["stale"]

def test_comparison_warns_about_timing_and_missing():
    now = datetime.now(timezone.utc)
    a = {"bid": 1, "ask": 1.2, "iv": .2, "quote_timestamp": now, "stale": False, "feed": "indicative"}
    b = {"bid": 2, "ask": 2.2, "iv": None, "quote_timestamp": now - timedelta(days=1), "stale": True}
    result = compare(a, b)
    assert result["significant_discrepancy"]
    assert result["timestamp_difference_seconds"] == 86400
    assert len(result["warnings"]) >= 3

def test_marketdata_hard_quota_does_not_retry(monkeypatch):
    calls = []
    class Response:
        status_code = 429
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs):
            calls.append(1)
            return Response()
    monkeypatch.setenv("MARKETDATA_API_TOKEN", "not-a-real-token")
    monkeypatch.setattr("app.market_providers.httpx.AsyncClient", Client)
    with pytest.raises(ProviderError, match="429"):
        asyncio.run(MarketDataProvider().quote("AAPL271217C00250000"))
    assert len(calls) == 1

def test_alpaca_requires_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(ProviderError, match="credentials"):
        AlpacaProvider()
def test_mocked_ingestion_and_verification(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    now = datetime.now(timezone.utc)
    class FakeAlpaca:
        option_feed = "indicative"
        async def bars(self, ticker):
            from app.market_models import Bar
            return [Bar(symbol=ticker, timestamp=now-timedelta(days=30-i), open=100+i, high=102+i, low=99+i, close=101+i, volume=100, source="alpaca", feed="iex") for i in range(25)]
        async def chain(self, ticker):
            return [OptionObservation(symbol="AAPL271217C00250000", underlying=ticker, expiration=date(2027,12,17), kind="call", strike=250, source="alpaca", feed="indicative", quote_timestamp=now, retrieved_at=now, bid=1, ask=1.2, iv=.3)]
    class FakeMarketData:
        async def quote(self, symbol):
            return OptionObservation(symbol=symbol, underlying="AAPL", expiration=date(2027,12,17), kind="call", strike=250, source="marketdata", feed="unknown", quote_timestamp=now-timedelta(days=1), retrieved_at=now, bid=2, ask=2.2, iv=.4)
    monkeypatch.setenv("PRIMARY_MARKET_DATA_PROVIDER", "alpaca")
    monkeypatch.setattr("app.market_api.AlpacaProvider", FakeAlpaca)
    monkeypatch.setattr("app.market_api.MarketDataProvider", FakeMarketData)
    with TestClient(app) as client:
        result = client.post("/ingest/AAPL")
        assert result.status_code == 200, result.text
        assert client.post("/ingest/AAPL").json()["new_option_quotes"] == 0
        chain = client.get("/securities/AAPL/options").json()
        assert chain[0]["feed"] == "indicative"
        verification = client.post("/securities/AAPL/options/AAPL271217C00250000/verify")
        assert verification.status_code == 200, verification.text
        assert verification.json()["significant_discrepancy"]
        assert verification.json()["timestamp_difference_seconds"] == 86400
        scenario = client.post("/scenarios/expiration", json={"kind":"call", "strike":100, "premium":5, "scenarios":[{"price":120, "probability":0.5}, {"price":90, "probability":0.5}]})
        assert scenario.json()["expected_value"] == 500
def test_stale_quotes_require_explicit_opt_in(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    now = datetime.now(timezone.utc)
    expiry = (now + timedelta(days=150)).date()
    symbol = "MSFT" + expiry.strftime("%y%m%d") + "C00100000"
    class FakeProvider:
        option_feed = "indicative"
        async def bars(self, ticker):
            from app.market_models import Bar
            return [Bar(symbol=ticker, timestamp=now-timedelta(days=30-i), open=100+i, high=102+i, low=99+i, close=101+i, volume=100, source="alpaca", feed="iex") for i in range(25)]
        async def chain(self, ticker):
            return [OptionObservation(symbol=symbol, underlying=ticker, expiration=expiry, kind="call", strike=100, source="alpaca", feed="indicative", quote_timestamp=now-timedelta(hours=1), retrieved_at=now, bid=1, ask=1.2, iv=.3)]
    monkeypatch.setenv("PRIMARY_MARKET_DATA_PROVIDER", "alpaca")
    monkeypatch.setattr("app.market_api.AlpacaProvider", FakeProvider)
    with TestClient(app) as client:
        assert client.post("/ingest/MSFT").status_code == 200
        assert not any(row["symbol"] == symbol for row in client.get("/scan").json())
        stale = next(row for row in client.get("/scan?include_stale=true").json() if row["symbol"] == symbol)
        assert stale["stale"] and "stale" in stale["warning"].lower()
        class FailedProvider:
            async def bars(self, ticker):
                raise ProviderError("quota reached")
        monkeypatch.setattr("app.market_api.AlpacaProvider", FailedProvider)
        assert client.post("/ingest/MSFT").status_code == 503
        assert any(row["symbol"] == symbol for row in client.get("/securities/MSFT/options").json())
