"""Resilient HTTP provider clients; provider errors never become invented data."""
from __future__ import annotations

import time
from typing import Any

import httpx

from .config import settings


class ProviderError(RuntimeError):
    pass


class HttpProvider:
    def __init__(self, timeout: float | None = None) -> None:
        self.timeout = timeout or settings.timeout_seconds

    def get_json(self, url: str, *, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, retries: int = 2) -> Any:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = httpx.get(url, params=params, headers=headers, timeout=self.timeout,
                                     follow_redirects=True)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(min(0.4 * (2 ** attempt), 2.0))
        raise ProviderError(f"Provider request failed: {type(last_error).__name__}: {last_error}") from last_error


class SecProvider(HttpProvider):
    def __init__(self) -> None:
        super().__init__()
        self.headers = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}

    def ticker_map(self) -> dict[str, dict[str, Any]]:
        data = self.get_json("https://www.sec.gov/files/company_tickers.json", headers=self.headers)
        return {str(row["ticker"]).upper(): row for row in data.values()}

    def company_facts(self, cik: str) -> dict[str, Any]:
        return self.get_json(f"{settings.sec_base_url}/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
                             headers=self.headers)

    def submissions(self, cik: str) -> dict[str, Any]:
        return self.get_json(f"{settings.sec_base_url}/submissions/CIK{int(cik):010d}.json",
                             headers=self.headers)


class MarketProvider(HttpProvider):
    def price_history(self, symbol: str, period: str = "1y") -> dict[str, Any]:
        return self.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                             params={"range": period, "interval": "1d"})

    def profile(self, symbol: str) -> dict[str, Any]:
        if not settings.finnhub_api_key:
            raise ProviderError("FINNHUB_API_KEY is not configured")
        return self.get_json("https://finnhub.io/api/v1/stock/profile2",
                             params={"symbol": symbol, "token": settings.finnhub_api_key})


class MacroProvider(HttpProvider):
    def series(self, series_id: str, limit: int = 24) -> dict[str, Any]:
        if not settings.fred_api_key:
            raise ProviderError("FRED_API_KEY is not configured")
        return self.get_json("https://api.stlouisfed.org/fred/series/observations",
                             params={"series_id": series_id, "api_key": settings.fred_api_key,
                                     "file_type": "json", "sort_order": "desc", "limit": limit})


class NewsProvider(HttpProvider):
    def search(self, query: str, page_size: int = 10) -> dict[str, Any]:
        if not settings.newsapi_api_key:
            raise ProviderError("NEWSAPI_API_KEY is not configured")
        return self.get_json("https://newsapi.org/v2/everything",
                             params={"q": query, "pageSize": page_size, "sortBy": "publishedAt",
                                     "apiKey": settings.newsapi_api_key})
