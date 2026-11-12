"""Public-data provider clients with transparent fallbacks and bounded retries."""
from __future__ import annotations

import csv
import io
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from .config import settings


class ProviderError(RuntimeError):
    """A remote data provider failed or returned unusable data."""


class HttpProvider:
    # Shared across provider instances and web requests in this process.
    _cache: dict[str, tuple[float, str]] = {}
    _cooldowns: dict[str, float] = {}
    _last_request: dict[str, float] = {}

    def __init__(self, timeout: float | None = None) -> None:
        self.timeout = timeout or settings.timeout_seconds

    @staticmethod
    def _cache_ttl(host: str) -> int:
        if "sec.gov" in host:
            return 300
        if "fred.stlouisfed.org" in host:
            return 1800
        if "finance.yahoo.com" in host or "query1.finance.yahoo.com" in host:
            return 60
        if "stooq.com" in host:
            return 180
        if "gdeltproject.org" in host or "news.google.com" in host:
            return 300
        return 60

    def _request(self, url: str, *, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, retries: int = 1) -> httpx.Response:
        request_headers = {"User-Agent": "ZethetaWorkBridge/0.3 (financial research)"}
        request_headers.update(headers or {})
        request = httpx.Request("GET", url, params=params, headers=request_headers)
        cache_key = str(request.url)
        host = request.url.host or ""
        now = time.monotonic()

        cached = self._cache.get(cache_key)
        if cached and cached[0] > now:
            return httpx.Response(200, text=cached[1], request=request)
        cooldown_until = self._cooldowns.get(host, 0)
        if cooldown_until > now:
            remaining = max(1, int(cooldown_until - now))
            raise ProviderError(f"{host} rate limit cooldown active ({remaining}s); using fallback or cached data")

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            # Keep requests to each public host spaced out across all provider instances.
            wait = 0.8 - (time.monotonic() - self._last_request.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()
            try:
                response = httpx.get(url, params=params, headers=request_headers,
                                     timeout=self.timeout, follow_redirects=True)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        cooldown = min(max(int(retry_after), 30), 300)
                    except ValueError:
                        cooldown = 90
                    self._cooldowns[host] = time.monotonic() + cooldown
                    raise ProviderError(f"{host} returned HTTP 429; cooling down for {cooldown}s")
                response.raise_for_status()
                self._cache[cache_key] = (
                    time.monotonic() + self._cache_ttl(host), response.text
                )
                self._cooldowns.pop(host, None)
                return response
            except (httpx.HTTPError, ProviderError) as exc:
                last_error = exc
                if "429" in str(exc) or "cooldown active" in str(exc):
                    break
                if attempt < retries:
                    time.sleep(min(0.8 * (2 ** attempt), 3.0))
        raise ProviderError(
            f"Provider request failed: {type(last_error).__name__}: {last_error}"
        ) from last_error

    def get_json(self, url: str, *, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, retries: int = 1) -> Any:
        try:
            return self._request(url, params=params, headers=headers, retries=retries).json()
        except ValueError as exc:
            raise ProviderError(f"Provider returned invalid JSON: {exc}") from exc

    def get_text(self, url: str, *, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, retries: int = 1) -> str:
        return self._request(url, params=params, headers=headers, retries=retries).text


class SecProvider(HttpProvider):
    def __init__(self) -> None:
        super().__init__()
        self.headers = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}

    def ticker_map(self) -> dict[str, dict[str, Any]]:
        data = self.get_json("https://www.sec.gov/files/company_tickers.json", headers=self.headers)
        return {str(row["ticker"]).upper(): row for row in data.values()}

    def company_facts(self, cik: str) -> dict[str, Any]:
        return self.get_json(
            f"{settings.sec_base_url}/api/xbrl/companyfacts/CIK{int(cik):010d}.json",
            headers=self.headers,
        )

    def submissions(self, cik: str) -> dict[str, Any]:
        return self.get_json(
            f"{settings.sec_base_url}/submissions/CIK{int(cik):010d}.json",
            headers=self.headers,
        )


class MarketProvider(HttpProvider):
    """Yahoo chart first, Stooq daily CSV fallback; both are live public endpoints."""

    def price_history(self, symbol: str, period: str = "1y") -> dict[str, Any]:
        ticker = symbol.upper().strip()
        yahoo_error: Exception | None = None
        try:
            data = self.get_json(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}",
                params={"range": period, "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0 WorkBridge research"},
                retries=0,
            )
            chart = data.get("chart", {}).get("result") or []
            if chart and chart[0].get("timestamp"):
                chart[0].setdefault("meta", {})["dataProvider"] = "Yahoo Finance"
                return data
            yahoo_error = ProviderError("Yahoo Finance returned no daily observations")
        except ProviderError as exc:
            yahoo_error = exc

        days = {"1mo": 40, "3mo": 100, "6mo": 190, "1y": 370, "2y": 740, "5y": 1850}
        end = datetime.now(UTC).date()
        start = end - timedelta(days=days.get(period, 370))
        stooq_symbol = f"{ticker.lower()}.us"
        try:
            text = self.get_text(
                "https://stooq.com/q/d/l/",
                params={"s": stooq_symbol, "i": "d", "d1": start.strftime("%Y%m%d"),
                        "d2": end.strftime("%Y%m%d")},
                headers={"User-Agent": "Mozilla/5.0 WorkBridge research"},
                retries=1,
            )
            rows = list(csv.DictReader(io.StringIO(text)))
            records = [row for row in rows if row.get("Date") and row.get("Close") not in (None, "", "N/D")]
            if not records:
                raise ProviderError(f"Stooq returned no daily prices for {ticker}")
            timestamps = [
                int(datetime.strptime(row["Date"], "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
                for row in records
            ]
            closes = [float(row["Close"]) for row in records]
            return {"chart": {"result": [{
                "meta": {"symbol": ticker, "currency": "USD", "dataProvider": "Stooq"},
                "timestamp": timestamps, "indicators": {"quote": [{"close": closes}]},
            }], "error": None}}
        except (ProviderError, ValueError, KeyError) as stooq_error:
            raise ProviderError(
                f"Yahoo Finance unavailable ({yahoo_error}); Stooq fallback unavailable ({stooq_error})"
            ) from stooq_error

    def profile(self, symbol: str) -> dict[str, Any]:
        if not settings.finnhub_api_key:
            raise ProviderError("Optional FINNHUB_API_KEY is not configured")
        return self.get_json(
            "https://finnhub.io/api/v1/stock/profile2",
            params={"symbol": symbol, "token": settings.finnhub_api_key},
        )


class MacroProvider(HttpProvider):
    """FRED public graph CSV endpoint; no API key is required."""

    def series(self, series_id: str, limit: int = 24) -> dict[str, Any]:
        text = self.get_text(
            "https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id}
        )
        rows = list(csv.DictReader(io.StringIO(text)))
        observations = [
            {"date": row.get("observation_date") or row.get("DATE"), "value": row.get(series_id)}
            for row in rows if row.get(series_id) not in (None, "", ".")
        ]
        observations = observations[-max(1, limit):]
        if not observations:
            raise ProviderError(f"FRED returned no observations for {series_id}")
        return {"observations": observations, "source": "FRED public graph CSV"}


class NewsProvider(HttpProvider):
    """GDELT first, Google News RSS fallback; both are public live news indexes."""

    def search(self, query: str, page_size: int = 10) -> dict[str, Any]:
        limit = min(max(page_size, 1), 50)
        try:
            data = self.get_json(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={"query": query, "mode": "ArtList", "format": "json",
                        "maxrecords": limit, "sort": "DateDesc"},
                retries=0,
            )
            normalized = []
            for article in data.get("articles", []):
                seen = article.get("seendate", "")
                published = (
                    f"{seen[:4]}-{seen[4:6]}-{seen[6:8]}T{seen[9:11]}:{seen[11:13]}:{seen[13:15]}Z"
                    if len(seen) >= 15 and seen[8:9] == "T" else None
                )
                normalized.append({
                    "title": article.get("title", "Untitled article"),
                    "description": article.get("socialimage") or article.get("domain"),
                    "publishedAt": published, "url": article.get("url"),
                    "source": {"name": article.get("domain") or "GDELT-indexed publisher"},
                })
            return {"articles": normalized, "source": "GDELT DOC 2.0"}
        except ProviderError as gdelt_error:
            # GDELT can throttle shared/public IPs. Fall back immediately rather
            # than retrying a known 429 and amplifying the rate limit.
            try:
                xml_text = self.get_text(
                    "https://news.google.com/rss/search",
                    params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
                    retries=0,
                )
                root = ET.fromstring(xml_text)
                articles = []
                for item in root.findall("./channel/item")[:limit]:
                    source = item.findtext("source") or "Google News publisher"
                    articles.append({
                        "title": item.findtext("title") or "Untitled article",
                        "description": source,
                        "publishedAt": item.findtext("pubDate"),
                        "url": item.findtext("link"),
                        "source": {"name": source},
                    })
                if articles:
                    return {"articles": articles, "source": "Google News RSS",
                            "fallback_reason": str(gdelt_error)}
                raise ProviderError("Google News RSS returned no matching articles")
            except (ProviderError, ET.ParseError) as fallback_error:
                raise ProviderError(
                    f"GDELT unavailable ({gdelt_error}); Google News RSS fallback unavailable ({fallback_error})"
                ) from fallback_error
