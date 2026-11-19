"""Run an isolated, rolled-back PostgreSQL paper-ledger smoke test.

The schema and all test rows are created inside one database transaction and
rolled back; no provider calls or persistent user records are created.
"""
from datetime import date, timedelta
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import sessionmaker
from app.db import Base, Contract, Security, engine
from app.main import app
import app.main as main_module
import app.paper_api as paper_module

schema = "paper_smoke_" + uuid4().hex
with engine.connect() as connection:
    transaction = connection.begin()
    try:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        Base.metadata.create_all(connection)
        test_session = sessionmaker(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        main_module.Session = test_session
        paper_module.Session = test_session
        with TestClient(app) as client:
            with test_session.begin() as db:
                security = db.scalar(select(Security).where(Security.ticker == "AAPL"))
                db.add(Contract(security_id=security.id, symbol="PAPER-SMOKE", expiration=date.today()+timedelta(days=365), kind="call", strike=100))
            assert client.post("/paper/account", json={"initial_cash":10000}).status_code == 201
            opened = client.post("/paper/positions", json={"request_id":str(uuid4()), "ticker":"AAPL", "symbol":"PAPER-SMOKE", "quantity":1, "price":5, "fee":0})
            assert opened.status_code == 201, opened.text
            assert client.get("/paper").json()["equity"] is None
            closed = client.post(f'/paper/positions/{opened.json()["id"]}/close', json={"request_id":str(uuid4()),"quantity":1,"price":3,"fee":0,"method":"sale"})
            assert closed.status_code == 200, closed.text
            assert client.get("/paper").json()["cash"] == 9800
    finally:
        transaction.rollback()
    assert not inspect(connection).has_schema(schema)
print("PostgreSQL paper ledger smoke test passed; transaction rolled back.")
