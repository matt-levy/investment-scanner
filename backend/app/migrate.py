"""Upgrade a new database or safely adopt the existing pre-Alembic schema."""
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, MetaData
from .db import Base, engine
from . import market_db, research_db, watchlist_db, paper_db  # register tables

def migrate():
    config = Config("alembic.ini")
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names()) - {"alembic_version"}
        # The initial baseline predates research tables; do not require future
        # tables when adopting a database created before Alembic existed.
        baseline = MetaData()
        for name, table in Base.metadata.tables.items():
            if name not in {"source_documents", "research_reports", "watchlist_items", "scenario_snapshots", "watchlist_assessments", "paper_accounts", "paper_positions", "paper_fills", "portfolio_valuations"}:
                table.to_metadata(baseline)
        expected = set(baseline.tables)
        if tables and "alembic_version" not in inspector.get_table_names():
            if tables != expected:
                raise RuntimeError("Existing database schema is incomplete or contains unexpected tables; migration stopped without changes.")
            differences = compare_metadata(MigrationContext.configure(connection), baseline)
            if differences:
                raise RuntimeError(f"Existing database differs from the expected schema; migration stopped: {differences}")
            # Stamp only after verifying the entire existing schema against this baseline.
            command.stamp(config, "b7a0b18fbb1a")
    command.upgrade(config, "head")

if __name__ == "__main__":
    migrate()
