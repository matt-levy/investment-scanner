import asyncio
import os
import httpx

class ProviderError(Exception):
    pass

class AlphaVantage:
    base_url = "https://www.alphavantage.co/query"

    async def query(self, function: str, ticker: str) -> dict:
        key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        if not key:
            raise ProviderError("ALPHA_VANTAGE_API_KEY is not configured.")
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(3):
                try:
                    response = await client.get(self.base_url, params={"function": function, "symbol": ticker, "apikey": key})
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                    response.raise_for_status()
                    data = response.json()
                    for field in ("Error Message", "Information", "Note"):
                        if field in data:
                            raise ProviderError(str(data[field]))
                    return data
                except (httpx.HTTPError, ValueError) as exc:
                    if attempt == 2:
                        raise ProviderError("Market data provider request failed.") from exc
                    await asyncio.sleep(2 ** attempt)
        raise ProviderError("Market data provider request failed.")

    async def prices(self, ticker: str) -> dict:
        return await self.query("TIME_SERIES_DAILY", ticker)

    async def options(self, ticker: str) -> dict:
        return await self.query("HISTORICAL_OPTIONS", ticker)
