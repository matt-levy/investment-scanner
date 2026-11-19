import os
from datetime import date, datetime, timezone
from sqlalchemy import create_engine, String, Float, Date, DateTime, ForeignKey, UniqueConstraint, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Base(DeclarativeBase):
    pass

class Security(Base):
    __tablename__ = "securities"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12), unique=True, index=True)

class Price(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (UniqueConstraint("security_id", "date", "source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    close: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Contract(Base):
    __tablename__ = "option_contracts"
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(80), unique=True)
    expiration: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(4))
    strike: Mapped[float] = mapped_column(Float)

class Quote(Base):
    __tablename__ = "option_quotes"
    __table_args__ = (UniqueConstraint("contract_id", "date", "source"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("option_contracts.id"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(40))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(12))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500))

engine = create_engine(os.getenv("DATABASE_URL", "postgresql+psycopg://scanner:scanner@localhost:5432/scanner"), pool_pre_ping=True)
Session = sessionmaker(bind=engine, expire_on_commit=False)
