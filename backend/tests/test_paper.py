from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.db import Contract, Security, Session
from app.main import app
from app.backtest_engine import EquityPoint, performance_metrics

def test_paper_account_partial_close_marks_and_settlement(monkeypatch):
    monkeypatch.setattr("app.paper_api.local_date", lambda: date(2026, 11, 17))
    monkeypatch.setattr("app.paper_api.latest_quote", lambda db, contract: {
        "bid": 6.0, "ask": 6.2, "stale": False, "feed": "indicative",
        "quote_timestamp": datetime.now(timezone.utc), "source": "alpaca"})
    with TestClient(app) as client:
        with Session.begin() as db:
            sec = db.scalar(select(Security).where(Security.ticker == "AAPL"))
            contract = Contract(security_id=sec.id, symbol="AAPL-PAPER-TEST", expiration=date(2027, 12, 17), kind="call", strike=100)
            db.add(contract)
        assert client.post("/paper/account", json={"initial_cash":10000}).status_code == 201
        assert client.post("/paper/account", json={"initial_cash":10000}).status_code == 409
        request_id = str(uuid4())
        opening = {"request_id":request_id,"ticker":"AAPL","symbol":"AAPL-PAPER-TEST","quantity":2,"price":5,"fee":2}
        position = client.post("/paper/positions", json=opening)
        assert position.status_code == 201
        position_id = position.json()["id"]
        assert client.post("/paper/positions", json=opening).json()["id"] == position_id
        assert client.post("/paper/positions", json={**opening,"price":4}).status_code == 409
        state = client.get("/paper").json()
        assert state["cash"] == pytest.approx(8998)
        assert state["equity"] == pytest.approx(10198)
        assert "not an executable" in state["positions"][0]["warnings"][0]
        close = {"request_id":str(uuid4()), "quantity":1, "price":7, "fee":1, "method":"sale"}
        partial = client.post(f"/paper/positions/{position_id}/close", json=close)
        assert partial.status_code == 200
        assert partial.json()["remaining_quantity"] == 1
        assert partial.json()["realized_profit"] == pytest.approx(198)
        assert client.post(f"/paper/positions/{position_id}/close", json=close).json()["remaining_quantity"] == 1
        assert client.post(f"/paper/positions/{position_id}/close", json={**close, "request_id":str(uuid4()), "quantity":2}).status_code == 422
        state = client.get("/paper").json()
        assert state["cash"] == pytest.approx(9697)
        assert state["equity"] == pytest.approx(10297)
        assert state["positions"][0]["unrealized_profit"] == pytest.approx(99)
        monkeypatch.setattr("app.paper_api.latest_quote", lambda db, contract: {"stale":True, "feed":"indicative", "bid":6, "ask":6.2})
        assert client.get("/paper").json()["equity"] is None
        assert client.post("/paper/valuations").json()["equity"] is None
        monkeypatch.setattr("app.paper_api.local_date", lambda: date(2027, 12, 18))
        assert client.post(f"/paper/positions/{position_id}/close", json={**close, "request_id":str(uuid4())}).status_code == 422
        settlement = client.post(f"/paper/positions/{position_id}/close", json={"request_id":str(uuid4()),"quantity":1,"price":0,"fee":0,"method":"settlement"})
        assert settlement.status_code == 200
        final = client.get("/paper").json()
        assert final["cash"] == pytest.approx(9697)
        assert final["equity"] == pytest.approx(9697)
        assert final["realized_profit"] == pytest.approx(-303)
        assert final["win_rate"] == 0
        assert final["benchmark"]["status"] == "unavailable"
        assert len(client.get("/paper/valuations").json()) == 1

def test_paper_cannot_buy_more_than_cash():
    with TestClient(app) as client:
        response = client.post("/paper/positions", json={"request_id":str(uuid4()),"ticker":"AAPL","symbol":"AAPL-PAPER-TEST","quantity":10000,"price":1000,"fee":0})
        assert response.status_code == 422

def test_backtest_metrics_and_refuses_lookahead():
    points = [EquityPoint(date(2026,1,d), portfolio, benchmark) for d, portfolio, benchmark in [(2,100,100),(3,120,105),(4,90,98),(5,110,102)]]
    result = performance_metrics(points, [.2, -.1], date(2026,1,2))
    assert result["total_return"] == pytest.approx(.1)
    assert result["benchmark_return"] == pytest.approx(.02)
    assert result["max_drawdown"] == pytest.approx(-.25)
    assert result["win_rate"] == .5
    assert result["average_return"] == pytest.approx(.05)
    with pytest.raises(ValueError):
        performance_metrics(points, [], date(2026,1,3))
    with pytest.raises(ValueError):
        performance_metrics(list(reversed(points)), [], date(2026,1,2))

def test_backtesting_is_blocked_without_validated_data():
    with TestClient(app) as client:
        status = client.get("/backtests/readiness").json()
        assert status["status"] == "incomplete"
        response = client.post("/backtests", json={"start":"2024-01-01", "out_of_sample_start":"2025-01-01", "end":"2026-01-01", "transaction_cost":1})
        assert response.status_code == 409
        assert response.json()["detail"]["status"] == "incomplete"
        assert client.post("/backtests", json={"start":"2025-01-01","out_of_sample_start":"2024-01-01","end":"2026-01-01","transaction_cost":1}).status_code == 422

def test_coverage_check_limits_request_and_reports_missing_signal(monkeypatch):
    import httpx
    calls = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return httpx.Response(203, headers={"X-Api-Ratelimit-Consumed": "1"}, json={"s":"ok", "optionSymbol":["sample"], "bid":[1], "ask":[2], "iv":[None]})
    monkeypatch.setenv("MARKETDATA_API_TOKEN", "private")
    monkeypatch.setattr("app.backtest_api.httpx.AsyncClient", FakeClient)
    with TestClient(app) as client:
        result = client.post("/backtests/coverage-check")
    assert result.status_code == 200
    assert result.json()["fields"]["bid"] is True
    assert result.json()["fields"]["iv"] is False
    assert result.json()["credits_consumed"] == "1"
    assert len(calls) == 1
    assert calls[0][1]["params"]["strikeLimit"] == "1"
    assert calls[0][1]["params"]["side"] == "call"
    assert "private" not in result.text

def test_replay_uses_only_available_oos_quotes_and_costs():
    from app.backtest_engine import ExecutionQuote, ScreeningSignal, UniverseMembership, IncompleteBacktestData, replay_signals
    utc = timezone.utc
    decision = datetime(2026,1,5,15,tzinfo=utc)
    signal = ScreeningSignal("OPT", "ABC", decision, decision-timedelta(minutes=1), date(2026,6,1), .2, .4)
    member = UniverseMembership("ABC", date(2020,1,1), date(2026,12,31), decision-timedelta(days=1))
    entry = ExecutionQuote("OPT", decision+timedelta(minutes=1), decision+timedelta(minutes=1), 4.9, 5, 10, 10, "opra")
    exit = ExecutionQuote("OPT", decision+timedelta(days=3, minutes=1), decision+timedelta(days=3, minutes=1), 7, 7.1, 10, 10, "opra")
    opts = {"out_of_sample_start":decision-timedelta(days=1), "out_of_sample_end":decision+timedelta(days=10), "holding_days":3, "cost_per_side":1, "max_spread":.2, "universe_history_verified":True}
    result = replay_signals([signal], [entry, exit], [member], **opts)
    assert result[0]["net_profit"] == 198
    assert result[0]["entry_at"] > result[0]["signal_at"]
    with pytest.raises(ValueError, match="not available"):
        replay_signals([ScreeningSignal("OPT","ABC",decision,decision+timedelta(days=1),date(2026,6,1),.2,.4)], [entry,exit], [member], **opts)
    with pytest.raises(IncompleteBacktestData, match="universe"):
        replay_signals([signal], [entry,exit], [member], **{**opts, "universe_history_verified":False})
    with pytest.raises(IncompleteBacktestData, match="entry"):
        replay_signals([signal], [ExecutionQuote("OPT",entry.timestamp,entry.available_at,4.9,5,10,10,"indicative"),exit], [member], **opts)
    with pytest.raises(IncompleteBacktestData, match="exit"):
        replay_signals([signal], [entry], [member], **opts)
