"""Source retrieval: SEC EDGAR and Alpaca news, with explicit provenance."""
import asyncio
import os
import re
import time
from datetime import date
from html.parser import HTMLParser
from urllib.parse import quote, urlparse
import httpx

class SourceError(Exception):
    pass

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.suppressed = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.suppressed += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.suppressed:
            self.suppressed -= 1
    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)

def clean_html(html: str, limit: int = 24000) -> tuple[str, str]:
    parser = TextExtractor()
    parser.feed(html)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    return text[:limit], "truncated_excerpt" if len(text) > limit else "full_text"

def public_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password

_sec_lock = asyncio.Lock()
_sec_last = 0.0
_ticker_cache: dict = {}
_ticker_cache_time = 0.0

async def sec_get(client: httpx.AsyncClient, url: str):
    global _sec_last
    async with _sec_lock:
        await asyncio.sleep(max(0, 0.2 - (time.monotonic() - _sec_last)))
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            raise SourceError("SEC request failed; try again later.") from exc
        finally:
            _sec_last = time.monotonic()
    if response.status_code in (403, 429):
        raise SourceError(f"SEC request returned HTTP {response.status_code}; check the identifying user agent or try later.")
    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SourceError(f"SEC request returned HTTP {response.status_code}.") from exc
    if len(response.content) > 8_000_000:
        raise SourceError("SEC response exceeds the retrieval size limit.")
    return response

async def sec_filings(ticker: str) -> list[dict]:
    global _ticker_cache, _ticker_cache_time
    agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not agent or "@" not in agent:
        raise SourceError("Set SEC_USER_AGENT to an identifying name and contact email.")
    async with httpx.AsyncClient(headers={"User-Agent": agent, "Accept-Encoding": "gzip, deflate"}, timeout=30, follow_redirects=False) as client:
        if not _ticker_cache or time.monotonic() - _ticker_cache_time > 86400:
            response = await sec_get(client, "https://www.sec.gov/files/company_tickers.json")
            try:
                mapping = response.json()
                _ticker_cache = {str(row["ticker"]).upper(): int(row["cik_str"]) for row in mapping.values()}
                _ticker_cache_time = time.monotonic()
            except (ValueError, KeyError, TypeError) as exc:
                raise SourceError("SEC ticker mapping is unavailable or malformed.") from exc
        cik = _ticker_cache.get(ticker)
        if cik is None:
            raise SourceError("No SEC company CIK found for this ticker; fund filings may use a different identifier.")
        response = await sec_get(client, f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        try:
            recent = response.json()["filings"]["recent"]
            records = []
            for idx, form in enumerate(recent["form"]):
                if form not in ("10-K", "10-Q", "8-K", "20-F", "6-K"):
                    continue
                accession = recent["accessionNumber"][idx]
                filename = recent["primaryDocument"][idx]
                if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(r"[A-Za-z0-9._-]+", filename):
                    continue
                records.append((form, accession, filename, recent["filingDate"][idx]))
                if len(records) >= 3:
                    break
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise SourceError("SEC submissions response is incomplete.") from exc
        result = []
        for form, accession, filename, filing_date in records:
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{quote(filename)}"
            try:
                filing = await sec_get(client, url)
                content, coverage = clean_html(filing.text)
                if not content:
                    continue
                result.append({"provider": "sec", "external_id": accession, "kind": form, "title": f"{ticker} {form} filed {filing_date}", "url": url, "published_on": date.fromisoformat(filing_date), "content": content, "coverage": coverage})
            except (SourceError, ValueError):
                # Other successfully retrieved filings remain available.
                continue
        if not result:
            raise SourceError("SEC submissions were found, but no filing text could be retrieved.")
        return result

async def alpaca_news(ticker: str) -> list[dict]:
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        raise SourceError("Alpaca credentials are not configured for news.")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get("https://data.alpaca.markets/v1beta1/news", headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}, params={"symbols": ticker, "limit": 10, "sort": "desc", "include_content": "false"})
            if response.status_code in (401, 403, 429):
                raise SourceError(f"Alpaca news returned HTTP {response.status_code}; check access or rate limits.")
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceError("Alpaca news request failed.") from exc
    result = []
    for item in data.get("news", []):
        url, title, identifier = item.get("url"), item.get("headline"), item.get("id")
        if not isinstance(url, str) or not public_url(url) or not title or identifier is None:
            continue
        summary, _ = clean_html(str(item.get("summary") or ""), 4000)
        content = str(title) + ("\n" + summary if summary else "")
        try:
            published = date.fromisoformat(str(item.get("created_at", ""))[:10])
        except ValueError:
            published = None
        result.append({"provider": "alpaca_news", "external_id": str(identifier), "kind": "news", "title": str(title)[:500], "url": url, "published_on": published, "content": content, "coverage": "headline_and_summary" if summary else "headline_only"})
    return result
