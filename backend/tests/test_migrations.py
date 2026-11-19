import os
import subprocess
import sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from app.db import Base
from app import market_db, research_db, watchlist_db, paper_db

BACKEND = Path(__file__).resolve().parents[1]

def run_migration(db_path):
    env = dict(os.environ, DATABASE_URL="sqlite:///" + db_path.as_posix())
    return subprocess.run([sys.executable, "-m", "app.migrate"], cwd=BACKEND, env=env, text=True, capture_output=True)

def test_migrate_new_and_existing_databases(tmp_path):
    fresh = tmp_path / "fresh.db"
    result = run_migration(fresh)
    assert result.returncode == 0, result.stderr
    engine = create_engine("sqlite:///" + fresh.as_posix())
    assert set(Base.metadata.tables) <= set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO securities (ticker) VALUES ('TEST')"))
    assert run_migration(fresh).returncode == 0
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM securities")) == 1
    existing = tmp_path / "existing.db"
    old_engine = create_engine("sqlite:///" + existing.as_posix())
    from sqlalchemy import MetaData
    baseline = MetaData()
    for name, table in Base.metadata.tables.items():
        if name not in {"source_documents", "research_reports", "watchlist_items", "scenario_snapshots", "watchlist_assessments", "paper_accounts", "paper_positions", "paper_fills", "portfolio_valuations"}:
            table.to_metadata(baseline)
    baseline.create_all(old_engine)
    with old_engine.begin() as conn:
        conn.execute(text("INSERT INTO securities (ticker) VALUES ('OLD')"))
    result = run_migration(existing)
    assert result.returncode == 0, result.stderr
    with old_engine.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM securities")) == 1
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "a080695fa588"

def test_migration_refuses_partial_unversioned_database(tmp_path):
    db_path = tmp_path / "partial.db"
    engine = create_engine("sqlite:///" + db_path.as_posix())
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE securities (id INTEGER PRIMARY KEY, ticker VARCHAR(12))"))
        conn.execute(text("INSERT INTO securities (ticker) VALUES ('KEEP')"))
    result = run_migration(db_path)
    assert result.returncode != 0
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT ticker FROM securities")) == "KEEP"
