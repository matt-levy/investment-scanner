"""Provider adapters. Network credentials remain server-side."""
import asyncio
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
import httpx
from .market_models import Bar, OptionObservation
from .provider import ProviderError

OCC = re.compile(r"^([A-Z.]{1,6})(\d{6})([CP])(\d{8})$")

def parse_occ(symbol: str) -> tuple[str, date, str, float]:
    match = OCC.fullmatch(symbol)
    if not match:
        raise ValueError("Unsupported option contract identifier")
    root, expiry, kind, strike = match.groups()
    return root, datetime.strptime(expiry, "%y%m%d").date(), "call" if kind == "C" else "put", int(strike) / 1000

class MarketProvider(Protocol):
    async def bars(self, ticker: str) -> list[Bar]: ...
    async def chain(self, ticker: str) -> list[OptionObservation]: ...

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def normalize_alpaca(symbol: str, underlying: str, snapshot, feed: str, retrieved: datetime) -> OptionObservation:
    root, expiration, kind, strike = parse_occ(symbol)
    if root != underlying:
        raise ValueError("Option root differs from underlying; adjusted contracts are not supported")
    quote = snapshot.latest_quote
    greeks = snapshot.greeks
    return OptionObservation(symbol=symbol, underlying=underlying, expiration=expiration, kind=kind, strike=strike,
        source="alpaca", feed=feed, quote_timestamp=quote.timestamp if quote else None, retrieved_at=retrieved,
        bid=quote.bid_price if quote else None, ask=quote.ask_price if quote else None,
        bid_size=quote.bid_size if quote else None, ask_size=quote.ask_size if quote else None,
        bid_exchange=str(quote.bid_exchange.value if hasattr(quote.bid_exchange, "value") else quote.bid_exchange) if quote and quote.bid_exchange else None, ask_exchange=str(quote.ask_exchange.value if hasattr(quote.ask_exchange, "value") else quote.ask_exchange) if quote and quote.ask_exchange else None,
        iv=snapshot.implied_volatility, delta=getattr(greeks, "delta", None), gamma=getattr(greeks, "gamma", None),
        theta=getattr(greeks, "theta", None), vega=getattr(greeks, "vega", None), rho=getattr(greeks, "rho", None))

class AlpacaProvider:
    def __init__(self):
        self.key = os.getenv("ALPACA_API_KEY", "")
        self.secret = os.getenv("ALPACA_SECRET_KEY", "")
        self.stock_feed = os.getenv("ALPACA_STOCK_FEED", "iex")
        self.option_feed = os.getenv("ALPACA_OPTIONS_FEED", "indicative")
        if not self.key or not self.secret:
            raise ProviderError("Alpaca credentials are not configured.")

    async def _call(self, operation):
        for attempt in range(3):
            try:
                return await asyncio.to_thread(operation)
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in (429, 401, 403) or (status is not None and status < 500) or attempt == 2:
                    raise ProviderError(f"Alpaca request failed (HTTP {status or 'unknown'}); check credentials, feed entitlement, and rate limits.") from exc
                await asyncio.sleep(2 ** attempt)
        raise ProviderError("Alpaca request failed.")

    async def bars(self, ticker: str) -> list[Bar]:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed
        now = utcnow()
        request = StockBarsRequest(symbol_or_symbols=ticker, timeframe=TimeFrame.Day, start=now - timedelta(days=180), end=now - timedelta(days=1), feed=DataFeed(self.stock_feed))
        client = StockHistoricalDataClient(self.key, self.secret)
        result = await self._call(lambda: client.get_stock_bars(request))
        return [Bar(symbol=ticker, timestamp=b.timestamp, open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume, source="alpaca", feed=self.stock_feed) for b in result.data.get(ticker, [])]

    async def chain(self, ticker: str) -> list[OptionObservation]:
        from alpaca.data.historical import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
        from alpaca.data.enums import OptionsFeed
        now = utcnow()
        request = OptionChainRequest(underlying_symbol=ticker, feed=OptionsFeed(self.option_feed), expiration_date_gte=(now + timedelta(days=90)).date(), expiration_date_lte=(now + timedelta(days=548)).date())
        client = OptionHistoricalDataClient(self.key, self.secret)
        result = await self._call(lambda: client.get_option_chain(request))
        observations = []
        for symbol, snapshot in result.items():
            try:
                observations.append(normalize_alpaca(symbol, ticker, snapshot, self.option_feed, now))
            except ValueError:
                continue
        return observations

    async def historical_trades(self, symbol: str, start: datetime, end: datetime):
        from alpaca.data.historical import OptionHistoricalDataClient
        from alpaca.data.requests import OptionTradesRequest
        parse_occ(symbol)
        client = OptionHistoricalDataClient(self.key, self.secret)
        result = await self._call(lambda: client.get_option_trades(OptionTradesRequest(symbol_or_symbols=symbol, start=start, end=end, limit=1000)))
        return [trade.model_dump(mode="json") for trade in result.data.get(symbol, [])]

    async def stock_snapshot(self, ticker: str):
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockSnapshotRequest
        from alpaca.data.enums import DataFeed
        client = StockHistoricalDataClient(self.key, self.secret)
        result = await self._call(lambda: client.get_stock_snapshot(StockSnapshotRequest(symbol_or_symbols=ticker, feed=DataFeed(self.stock_feed))))
        snapshot = result.get(ticker)
        return snapshot.model_dump(mode="json") if snapshot else None

class MarketDataProvider:
    def __init__(self):
        self.token = os.getenv("MARKETDATA_API_TOKEN", "")
        if not self.token:
            raise ProviderError("MarketData.app token is not configured.")

    async def quote(self, symbol: str, historical_date: date | None = None) -> OptionObservation:
        underlying, expiration, kind, strike = parse_occ(symbol)
        params = {"date": historical_date.isoformat()} if historical_date else {}
        async with httpx.AsyncClient(timeout=20) as client:
            for attempt in range(3):
                try:
                    response = await client.get(f"https://api.marketdata.app/v1/options/quotes/{symbol}/", headers={"Authorization": f"Bearer {self.token}"}, params=params)
                    if response.status_code in (401, 403, 429):
                        raise ProviderError(f"MarketData.app returned HTTP {response.status_code}; check entitlement or credits.")
                    if response.status_code >= 500 and attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    if data.get("s") != "ok":
                        raise ProviderError("MarketData.app returned no quote or the request is not entitled.")
                    def first(name):
                        value = data.get(name)
                        return value[0] if isinstance(value, list) and value else None
                    if first("optionSymbol") != symbol:
                        raise ProviderError("MarketData.app returned a different contract.")
                    updated = first("updated")
                    return OptionObservation(symbol=symbol, underlying=underlying, expiration=expiration, kind=kind, strike=strike, source="marketdata", feed="provider-entitlement-unknown", classification="historical" if historical_date else "unknown", quote_timestamp=datetime.fromtimestamp(updated, timezone.utc) if updated is not None else None, retrieved_at=utcnow(), bid=first("bid"), ask=first("ask"), bid_size=first("bidSize"), ask_size=first("askSize"), iv=first("iv"), delta=first("delta"), gamma=first("gamma"), theta=first("theta"), vega=first("vega"), volume=first("volume"), open_interest=first("openInterest"))
                except (httpx.HTTPError, ValueError) as exc:
                    if attempt == 2:
                        raise ProviderError("MarketData.app request failed.") from exc
                    await asyncio.sleep(2 ** attempt)
        raise ProviderError("MarketData.app request failed.")

