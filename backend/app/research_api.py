import hashlib
import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from .db import Security, Session
from .research_db import ResearchReport, SourceDocument
from .research_llm import OpenAICompatibleProvider, ProviderError
from .research_sources import SourceError, alpaca_news, sec_filings

router = APIRouter(prefix="/research", tags=["research"])

class ReportRequest(BaseModel):
    source_ids: list[int] = Field(min_length=1, max_length=8)

def security(db, ticker):
    result = db.scalar(select(Security).where(Security.ticker == ticker.upper()))
    if not result:
        raise HTTPException(404, "Ticker is outside the configured universe.")
    return result

def source_json(source):
    return {"id": source.id, "provider": source.provider, "kind": source.kind, "title": source.title, "url": source.url,
        "published_on": source.published_on, "retrieved_at": source.retrieved_at, "coverage": source.coverage, "content": source.content}

def report_json(report):
    return {"id": report.id, "created_at": report.created_at, "provider": report.provider, "model": report.model,
        "source_ids": report.source_ids, "report": report.report,
        "disclaimer": "AI-generated interpretations and hypotheses; exact quotations are checked, but claims and conclusions require human review."}

@router.get("/status")
def status():
    return {"sec_configured": bool(os.getenv("SEC_USER_AGENT", "").strip() and "@" in os.getenv("SEC_USER_AGENT", "")),
        "news_configured": bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY")),
        "llm_configured": bool(os.getenv("LLM_BASE_URL") and os.getenv("LLM_MODEL"))}

@router.get("/{ticker}/sources")
def list_sources(ticker: str):
    with Session() as db:
        sec = security(db, ticker)
        rows = db.scalars(select(SourceDocument).where(SourceDocument.security_id == sec.id).order_by(SourceDocument.retrieved_at.desc(), SourceDocument.id.desc()).limit(100))
        return [source_json(item) for item in rows]

@router.post("/{ticker}/sources/refresh")
async def refresh_sources(ticker: str, force: bool = False):
    with Session() as db:
        ticker = security(db, ticker).ticker
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        cached_providers = set(db.scalars(select(SourceDocument.provider).join(Security).where(Security.ticker == ticker, SourceDocument.retrieved_at >= cutoff)).all())
    results, errors, cached = [], {}, []
    for provider, fetch in (("sec", sec_filings), ("alpaca_news", alpaca_news)):
        if not force and provider in cached_providers:
            cached.append(provider)
            continue
        try:
            records = await fetch(ticker)
            results.extend(records)
        except SourceError as exc:
            errors[provider] = str(exc)
    saved = 0
    with Session.begin() as db:
        sec = security(db, ticker)
        for row in results:
            digest = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
            old = db.scalar(select(SourceDocument).where(SourceDocument.security_id == sec.id, SourceDocument.provider == row["provider"], SourceDocument.external_id == row["external_id"], SourceDocument.content_hash == digest))
            if not old:
                db.add(SourceDocument(security_id=sec.id, content_hash=digest, **row))
                saved += 1
    return {"ticker": ticker, "new_sources": saved, "cached_providers": cached, "errors": errors}

@router.get("/{ticker}/reports")
def list_reports(ticker: str):
    with Session() as db:
        sec = security(db, ticker)
        return [report_json(r) for r in db.scalars(select(ResearchReport).where(ResearchReport.security_id == sec.id).order_by(ResearchReport.id.desc()).limit(20))]

@router.post("/{ticker}/reports", status_code=201)
async def generate_report(ticker: str, request: ReportRequest):
    ids = list(dict.fromkeys(request.source_ids))
    with Session() as db:
        sec = security(db, ticker)
        docs = list(db.scalars(select(SourceDocument).where(SourceDocument.security_id == sec.id, SourceDocument.id.in_(ids))))
        if len(docs) != len(ids):
            raise HTTPException(422, "All selected sources must exist and belong to this ticker.")
        # Only these exact excerpts may be cited; coverage is displayed to the user.
        documents = [{"id": d.id, "title": d.title, "published_on": str(d.published_on) if d.published_on else None,
                      "coverage": d.coverage, "content": d.content[:6000]} for d in docs]
    try:
        body, provider, model = await OpenAICompatibleProvider().generate(documents)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc
    with Session.begin() as db:
        sec = security(db, ticker)
        report = ResearchReport(security_id=sec.id, provider=provider, model=model, source_ids=ids, report=body.model_dump())
        db.add(report)
        db.flush()
        return report_json(report)
