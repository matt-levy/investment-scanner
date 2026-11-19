from datetime import date, datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.db import Contract, Security, Session
from app.main import app
from app.market_models import OptionObservation
from app.market_service import persist_quote
from app.ranking import screen_factors

def test_ranking_is_explicit_and_missing_data_is_not_rewarded():
    quote = {"iv": .2, "spread": .1, "bid": 1, "ask": 1.1, "quote_timestamp": "known", "volume": None, "open_interest": None, "stale": False}
    factors = screen_factors(quote, .4)
    assert factors["volatility_factor"] == 50
    assert factors["spread_factor"] == 80
    assert factors["completeness_factor"] == round(100 * 5 / 7, 1)
    assert factors["score"] == round(.4 * 50 + .4 * 80 + .2 * (100 * 5 / 7), 1)
    assert factors["expected_value"] == "not assessed"
    assert screen_factors(quote, 0)["score"] is None
    stale = screen_factors({**quote, "stale": True}, .4)
    assert stale["completeness_factor"] < factors["completeness_factor"]

def test_watchlist_scenario_versions_and_archival(monkeypatch):
    monkeypatch.setenv("PRIMARY_MARKET_DATA_PROVIDER", "alpaca")
    now = datetime.now(timezone.utc)
    symbol = "AAPL281215C00100000"
    with TestClient(app) as client:
        with Session.begin() as db:
            sec = db.scalar(select(Security).where(Security.ticker == "AAPL"))
            contract = db.scalar(select(Contract).where(Contract.symbol == symbol))
            if not contract:
                contract = Contract(security_id=sec.id, symbol=symbol, expiration=date(2028,12,15), kind="call", strike=100)
                db.add(contract)
                db.flush()
            obs = OptionObservation(symbol=symbol, underlying="AAPL", expiration=date(2028,12,15), kind="call", strike=100, source="alpaca", feed="indicative", quote_timestamp=now-timedelta(minutes=1), retrieved_at=now, bid=4.9, ask=5, iv=.3)
            persist_quote(db, sec, obs)
        item = client.post("/watchlist", json={"ticker":"AAPL","symbol":symbol})
        assert item.status_code == 201
        item_id = item.json()["id"]
        assert client.post("/watchlist", json={"ticker":"MSFT","symbol":symbol}).status_code == 404
        assumptions = {"premium":5, "transaction_cost":10, "scenarios":[{"name":"Bullish","price":120,"probability":.25},{"name":"Neutral","price":100,"probability":.5},{"name":"Bearish","price":80,"probability":.25}]}
        calculated = client.post(f"/watchlist/{item_id}/calculate", json=assumptions)
        assert calculated.status_code == 200
        assert calculated.json()["expected_value"] == -10
        assert [x["net_profit"] for x in calculated.json()["outcomes"]] == [1490, -510, -510]
        assert client.post(f"/watchlist/{item_id}/scenarios", json={**assumptions, "scenarios": assumptions["scenarios"][:2]}).status_code == 422
        first = client.post(f"/watchlist/{item_id}/scenarios", json=assumptions).json()
        assert first["quote_snapshot"]["ask"] == 5
        second = client.post(f"/watchlist/{item_id}/scenarios", json={**assumptions, "premium":6}).json()
        assert second["id"] != first["id"]
        history = client.get(f"/watchlist/{item_id}/scenarios").json()
        assert [s["assumptions"]["premium"] for s in history] == [6,5]
        assert client.delete(f"/watchlist/{item_id}").status_code == 204
        assert client.get(f"/watchlist/{item_id}/scenarios").status_code == 404
        assert client.post("/watchlist", json={"ticker":"AAPL","symbol":symbol}).json()["id"] == item_id
        assert len(client.get(f"/watchlist/{item_id}/scenarios").json()) == 2
        assert len(client.get(f"/watchlist/{item_id}/quotes").json()) == 1

def test_two_outcome_break_even_probability():
    from types import SimpleNamespace
    from app.watchlist_api import Assumptions, scenario_result
    contract = SimpleNamespace(kind="call", strike=100, expiration=date(2028, 12, 15))
    request = Assumptions.model_validate({"premium":5,"transaction_cost":0,"scenarios":[{"name":"up","price":120,"probability":.5},{"name":"down","price":90,"probability":.5}]})
    assert scenario_result(contract, request)["break_even_probability"] == .25


def test_watchlist_delete_cors_preflight():
    with TestClient(app) as client:
        response = client.options("/watchlist/1", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "DELETE",
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "DELETE" in response.headers["access-control-allow-methods"]
def test_black_scholes_reference_and_expiration():
    from app.analytics import european_option_value
    import pytest
    assert european_option_value("call", 100, 100, 1, .2, .05, 0) == pytest.approx(10.45058357, abs=1e-6)
    assert european_option_value("put", 100, 100, 1, .2, .05, 0) == pytest.approx(5.573526, abs=1e-6)
    assert european_option_value("put", 80, 100, 0, .2, .05, 0) == 20
    assert european_option_value("call", 0, 100, 1, .2, .05, 0) == 0

def test_pre_expiration_scenario_requires_assumptions():
    from types import SimpleNamespace
    import pytest
    from fastapi import HTTPException
    from app.watchlist_api import Assumptions, scenario_result
    contract = SimpleNamespace(kind="call", strike=100, expiration=date(2028,1,1))
    data = {"premium":5, "transaction_cost":10, "valuation_date":"2027-01-01", "risk_free_rate":.05, "dividend_yield":0,
            "scenarios":[{"name":"up","price":100,"probability":.5,"volatility":.2},{"name":"down","price":80,"probability":.5,"volatility":.3}]}
    result = scenario_result(contract, Assumptions.model_validate(data))
    assert result["model"] == "European Black-Scholes-Merton"
    assert result["outcomes"][0]["option_value"] == pytest.approx(10.45058357, abs=1e-6)
    assert result["outcomes"][0]["net_profit"] == pytest.approx((10.45058357 - 5) * 100 - 10, abs=1e-4)
    with pytest.raises(HTTPException):
        scenario_result(contract, Assumptions.model_validate({**data, "risk_free_rate": None}))
    with pytest.raises(HTTPException):
        scenario_result(contract, Assumptions.model_validate({**data, "valuation_date":"2028-01-02"}))

def test_user_assessment_requires_owned_source_and_priority():
    import pytest
    from pydantic import ValidationError
    from app.watchlist_api import AssessmentRequest
    from app.ranking import watchlist_priority
    with pytest.raises(ValidationError):
        AssessmentRequest.model_validate({"catalyst_relevance":"high", "evidence_quality":"strong", "source_ids":[]})
    result = watchlist_priority(80, 100, 500, "high", "mixed", True)
    assert result["score"] == 74.5
    assert result["expected_value_factor"] == 60
    assert watchlist_priority(80, 100, 500, "unknown", "mixed", True)["score"] is None
    assert watchlist_priority(80, 100, 500, "high", "mixed", False)["score"] is None
def test_assessment_is_source_linked_versioned_and_ticker_scoped():
    from app.research_db import SourceDocument
    with TestClient(app) as client:
        with Session.begin() as db:
            aapl = db.scalar(select(Security).where(Security.ticker == "AAPL"))
            msft = db.scalar(select(Security).where(Security.ticker == "MSFT"))
            contract = Contract(security_id=aapl.id, symbol="AAPL281215P00101000", expiration=date(2028,12,15), kind="put", strike=101)
            db.add(contract)
            doc = SourceDocument(security_id=aapl.id, provider="test", external_id="phase3-aapl", kind="10-K", title="AAPL source", url="https://www.sec.gov/example", published_on=date(2026,1,1), content_hash="a"*64, content="Example source text for manual review.", coverage="full_text")
            other = SourceDocument(security_id=msft.id, provider="test", external_id="phase3-msft", kind="10-K", title="MSFT source", url="https://www.sec.gov/example", published_on=date(2026,1,1), content_hash="b"*64, content="Unrelated source text.", coverage="full_text")
            db.add_all([doc, other])
            db.flush()
            doc_id, other_id = doc.id, other.id
        item_id = client.post("/watchlist", json={"ticker":"AAPL","symbol":"AAPL281215P00101000"}).json()["id"]
        payload = {"catalyst_relevance":"high", "evidence_quality":"mixed", "notes":"My assessment", "source_ids":[doc_id]}
        assert client.post(f"/watchlist/{item_id}/assessments", json={**payload, "source_ids":[other_id]}).status_code == 422
        assert client.post(f"/watchlist/{item_id}/assessments", json=payload).status_code == 201
        assert client.post(f"/watchlist/{item_id}/assessments", json={**payload, "evidence_quality":"weak"}).status_code == 201
        saved = client.get(f"/watchlist/{item_id}/assessments").json()
        assert [s["inputs"]["evidence_quality"] for s in saved] == ["weak", "mixed"]
        item = next(row for row in client.get("/watchlist").json() if row["id"] == item_id)
        assert item["priority"]["score"] is None  # no quote, scenario or realized volatility
        assert item["research_assessment"]["source_ids"] == [doc_id]
def test_priority_uses_saved_user_inputs_and_fresh_observations(monkeypatch):
    from app.market_db import MarketBar
    from app.market_models import Bar
    from app.market_service import persist_bar
    from app.research_db import SourceDocument
    monkeypatch.setenv("PRIMARY_MARKET_DATA_PROVIDER", "alpaca")
    now = datetime.now(timezone.utc)
    expiry = (now + timedelta(days=365)).date()
    symbol = "AAPL-PRIORITY-TEST"
    with TestClient(app) as client:
        with Session.begin() as db:
            sec = db.scalar(select(Security).where(Security.ticker == "AAPL"))
            doc = SourceDocument(security_id=sec.id, provider="test", external_id="priority", kind="10-K", title="Source", url="https://www.sec.gov/example", published_on=now.date(), content_hash="c"*64, content="Evidence for review.", coverage="full_text")
            db.add(doc)
            db.flush()
            doc_id = doc.id
            for i in range(21):
                timestamp = now - timedelta(days=20-i)
                price = 100 + i + (i % 3)
                persist_bar(db, sec, Bar(symbol="AAPL", timestamp=timestamp, open=price, high=price, low=price, close=price, volume=10, source="alpaca", feed="iex"))
            persist_quote(db, sec, OptionObservation(symbol=symbol, underlying="AAPL", expiration=expiry, kind="call", strike=100, source="alpaca", feed="indicative", quote_timestamp=now, retrieved_at=now, bid=4.9, ask=5, iv=.3))
        item_id = client.post("/watchlist", json={"ticker":"AAPL","symbol":symbol}).json()["id"]
        payload = {"premium":5, "transaction_cost":0, "scenarios":[{"name":"up","price":120,"probability":.5},{"name":"down","price":90,"probability":.5}]}
        assert client.post(f"/watchlist/{item_id}/scenarios", json=payload).status_code == 201
        assert client.post(f"/watchlist/{item_id}/assessments", json={"catalyst_relevance":"high", "evidence_quality":"mixed", "source_ids":[doc_id]}).status_code == 201
        row = next(item for item in client.get("/watchlist").json() if item["id"] == item_id)
        assert row["priority"]["score"] is not None
        assert row["priority"]["catalyst_factor"] == 100
        assert row["priority"]["evidence_factor"] == 50
        assert row["priority"]["scenario_id"] and row["priority"]["assessment_id"]
        assert row["priority"]["bars_fresh"]
