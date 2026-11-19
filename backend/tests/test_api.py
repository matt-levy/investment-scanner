from fastapi.testclient import TestClient
from app.main import app

def test_payoff_api():
    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.post("/payoff", json={"kind": "call", "strike": 100, "premium": 5, "price": 120})
        assert response.status_code == 200
        assert response.json()["net_profit"] == 1500
        assert response.json()["break_even"] == 105
        assert client.post("/payoff", json={"kind": "call", "strike": -1, "premium": 5, "price": 120}).status_code == 422

def test_empty_universe():
    with TestClient(app) as client:
        assert len(client.get("/securities").json()) == 5
        assert client.get("/scan").json() == []
        assert client.get("/securities/UNKNOWN").status_code == 404
