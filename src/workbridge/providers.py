"""Public-data provider clients with transparent fallbacks and bounded retries."""
from __future__ import annotations

import csv
import io
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from .config import refresh_optional_api_keys, settings


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
        request_url = httpx.URL(url).copy_merge_params(params or {})
        request = httpx.Request("GET", request_url, headers=request_headers)
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

    # Common abbreviated search terms that Yahoo can misinterpret as unrelated
    # US tickers. Resolve these to the issuer name before asking its symbol directory.
    _issuer_search_aliases = {
        "SOUTH": "South Indian Bank",
        "SOUTHBANK": "South Indian Bank",
        "SOUTH BANK": "South Indian Bank",
        "SOUTH INDIAN BANK LIMITED": "South Indian Bank",
        "SOUTH INDIAN BANK LTD": "South Indian Bank",
    }

    def search_symbols(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Resolve a company name or ticker to exchange-qualified Yahoo symbols."""
        cleaned = " ".join(query.split())
        cleaned = self._issuer_search_aliases.get(cleaned.upper(), cleaned)
        if not cleaned:
            return []
        data = self.get_json(
            "https://query1.finance.yahoo.com/v1/finance/search",
            params={"q": cleaned, "quotesCount": min(max(limit, 1), 15),
                    "newsCount": 0, "enableFuzzyQuery": "true"},
            headers={"User-Agent": "Mozilla/5.0 QYRAVEX financial research"},
            retries=0,
        )
        candidates = []
        for item in data.get("quotes", []):
            if item.get("quoteType") not in {"EQUITY", "ETF", "INDEX"}:
                continue
            symbol = item.get("symbol")
            if not symbol:
                continue
            candidates.append({
                "symbol": symbol,
                "name": item.get("longname") or item.get("shortname") or symbol,
                "exchange": item.get("exchDisp") or item.get("exchange") or "Exchange not supplied",
                "exchange_code": item.get("exch") or "",
                "quote_type": item.get("quoteType"),
                "currency": item.get("currency"),
                "source": "Yahoo Finance symbol search",
                "source_url": f"https://finance.yahoo.com/quote/{quote(symbol)}",
            })
        return candidates

    def price_history(self, symbol: str, period: str = "1y") -> dict[str, Any]:
        ticker = symbol.upper().strip()
        yahoo_error: Exception | None = None
        try:
            data = self.get_json(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker)}",
                params={"range": period, "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0 QYRAVEX financial research"},
                retries=0,
            )
            chart = data.get("chart", {}).get("result") or []
            if chart and chart[0].get("timestamp"):
                chart[0].setdefault("meta", {})["dataProvider"] = "Yahoo Finance"
                return data
            yahoo_error = ProviderError("Yahoo Finance returned no daily observations")
        except ProviderError as exc:
            yahoo_error = exc

        # Resolve company names and exchange-qualified listings before failing.
        resolved = None
        try:
            candidates = self.search_symbols(symbol)
            exact = [item for item in candidates if item["symbol"].upper() == ticker]
            resolved = (exact or candidates)[0] if candidates else None
            if resolved and resolved["symbol"].upper() != ticker:
                data = self.get_json(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(resolved['symbol'])}",
                    params={"range": period, "interval": "1d"},
                    headers={"User-Agent": "Mozilla/5.0 QYRAVEX financial research"},
                    retries=0,
                )
                chart = data.get("chart", {}).get("result") or []
                if chart and chart[0].get("timestamp"):
                    chart[0].setdefault("meta", {})["dataProvider"] = "Yahoo Finance"
                    chart[0]["meta"]["resolvedFrom"] = ticker
                    chart[0]["meta"]["symbolSearch"] = resolved
                    return data
        except ProviderError as exc:
            yahoo_error = exc

        # Stooq .us is only meaningful for US listings; never invent it for
        # an international ticker such as NSE (.NS) or BSE (.BO).
        if "." in ticker or (resolved and resolved.get("exchange_code") not in {"NMS", "NYQ", "ASE", "NGM", "NCM", "PCX"}):
            detail = f"Yahoo Finance could not verify a price series for {ticker}"
            if resolved:
                detail += f" (candidate: {resolved['name']} / {resolved['symbol']})"
            raise ProviderError(f"{detail}: {yahoo_error}")

        days = {"1mo": 40, "3mo": 100, "6mo": 190, "1y": 370, "2y": 740, "5y": 1850}
        end = datetime.now(UTC).date()
        start = end - timedelta(days=days.get(period, 370))
        stooq_symbol = f"{ticker.lower()}.us"
        try:
            text = self.get_text(
                "https://stooq.com/q/d/l/",
                params={"s": stooq_symbol, "i": "d", "d1": start.strftime("%Y%m%d"),
                        "d2": end.strftime("%Y%m%d")},
                headers={"User-Agent": "Mozilla/5.0 QYRAVEX financial research"},
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

    def quote(self, symbol: str) -> dict[str, Any]:
        refresh_optional_api_keys()
        if not settings.finnhub_api_key:
            raise ProviderError("Optional FINNHUB_API_KEY is not configured")
        data = self.get_json(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol.upper(), "token": settings.finnhub_api_key},
            retries=0,
        )
        if not data.get("c"):
            raise ProviderError(f"Finnhub returned no live quote for {symbol}")
        return data

    def profile(self, symbol: str) -> dict[str, Any]:
        refresh_optional_api_keys()
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


class AIResearchProvider:
    """Optional independent LLM reviewers; they interpret evidence, never invent market data."""

    def analyze(self, *, company: str, symbol: str, horizon: int,
                market_facts: dict[str, Any], articles: list[dict[str, Any]]) -> dict[str, Any]:
        refresh_optional_api_keys()
        evidence = {
            "issuer": company, "symbol": symbol, "horizon_trading_days": horizon,
            "quantitative_market_facts": market_facts,
            "indexed_news": [{
                "title": item.get("title"),
                "description": (item.get("description") or "")[:1200],
                "publisher": (item.get("source") or {}).get("name"),
                "published_at": item.get("publishedAt"), "url": item.get("url"),
            } for item in articles[:12]],
        }
        prompt = (
            "You are a cautious equity research analyst. Analyze ONLY the supplied evidence. "
            "Do not invent facts, prices, financial statements, sources, or probabilities. "
            "Return concise plain text with: directional_bias (bullish/bearish/mixed/insufficient), "
            "key_catalysts, material_risks, evidence_gaps, and confidence (low/medium/high). "
            "If the evidence is insufficient, say so. This is not investment advice.\n"
            + str(evidence)
        )
        results: list[dict[str, str]] = []
        errors: list[str] = []
        if settings.openai_api_key:
            try:
                response = httpx.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={"model": "gpt-5.5",
                          "messages": [{"role": "user", "content": prompt}]},
                    timeout=8.0,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if content:
                    results.append({"provider": "OpenAI", "analysis": str(content)})
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"OpenAI: {type(exc).__name__}: {exc}")
        if settings.gemini_api_key:
            try:
                response = httpx.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
                    params={"key": settings.gemini_api_key},
                    json={"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {"temperature": 0.1}},
                    timeout=12.0,
                )
                response.raise_for_status()
                content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                if content:
                    results.append({"provider": "Google Gemini", "analysis": str(content)})
            except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
                errors.append(f"Google Gemini: {type(exc).__name__}: {exc}")
        if settings.anthropic_api_key:
            try:
                response = httpx.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": settings.anthropic_api_key,
                             "anthropic-version": "2023-06-01"},
                    json={"model": "claude-haiku-5-5", "max_tokens": 700,
                          "temperature": 0.1, "messages": [{"role": "user", "content": prompt}]},
                    timeout=12.0,
                )
                response.raise_for_status()
                content = response.json()["content"][0]["text"]
                if content:
                    results.append({"provider": "Anthropic Claude", "analysis": str(content)})
            except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
                errors.append(f"Anthropic Claude: {type(exc).__name__}: {exc}")
        return {
            "enabled_providers": [
                name for name, key in (
                    ("OpenAI", settings.openai_api_key),
                    ("Google Gemini", settings.gemini_api_key),
                    ("Anthropic Claude", settings.anthropic_api_key),
                ) if key
            ],
            "successful_providers": [item["provider"] for item in results],
            "analyses": results,
            "errors": errors,
            "mode": "independent evidence-grounded reviews; model outputs do not alter the quantitative price scenarios",
        }


class NewsProvider(HttpProvider):
    """Aggregate public news indexes and optional licensed news APIs."""

    def __init__(self) -> None:
        # A slow news index must not stall the whole research run for the global
        # 20-second default timeout. Other providers are still attempted.
        super().__init__(timeout=min(settings.timeout_seconds, 6.0))

    _cache: dict[str, tuple[float, dict[str, Any]]] = {}
    _cache_lock = threading.Lock()
    cache_ttl_seconds = 180

    def search(self, query: str, page_size: int = 30) -> dict[str, Any]:
        refresh_optional_api_keys()
        normalized_query = " ".join(query.split()).casefold()
        limit = min(max(page_size, 1), 50)
        cache_key = f"{normalized_query}:{limit}"
        now = time.time()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self.cache_ttl_seconds:
                result = dict(cached[1])
                result["cached"] = True
                return result

        articles: list[dict[str, Any]] = []
        providers: list[str] = []
        errors: list[str] = []

        # Independent providers are attempted separately: one outage must not hide
        # results already obtained from another source.
        try:
            data = self.get_json(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={"query": query, "mode": "ArtList", "format": "json",
                        "maxrecords": limit, "sort": "DateDesc"},
                retries=0,
            )
            found = self._normalize_gdelt(data.get("articles", []))
            if found:
                articles.extend(found)
                providers.append("GDELT DOC 2.0")
        except (ProviderError, httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            # Keep fallback discovery alive even when a transport mock or an
            # unexpected HTTP client path surfaces the raw httpx exception.
            errors.append(f"GDELT: {type(exc).__name__}: {exc}")

        try:
            found = self._google_news_rss(query, limit)["articles"]
            articles.extend(found)
            providers.append("Google News RSS")
        except ProviderError as exc:
            errors.append(f"Google News RSS: {exc}")

        ticker = self._ticker_from_query(query)
        # Broad issuer-name searches avoid the false-negative behavior of an
        # exact quoted company phrase followed by unrelated prompt wording.
        search_queries = self._issuer_queries(query, ticker)
        for alternate_query in search_queries:
            if alternate_query.casefold() == query.casefold():
                continue
            try:
                found = self._google_news_rss(alternate_query, limit)["articles"]
                articles.extend(found)
                providers.append("Google News RSS (issuer fallback)")
                break
            except ProviderError as exc:
                errors.append(f"Google News RSS issuer fallback: {exc}")

        # Bing News RSS is an additional public index; use the issuer's home
        # market for India-listed companies to avoid US-centric false negatives.
        if not articles:
            for alternate_query in search_queries[:3] or [query]:
                try:
                    found = self._bing_news_rss(alternate_query, limit)["articles"]
                    articles.extend(found)
                    providers.append("Bing News RSS")
                    break
                except ProviderError as exc:
                    errors.append(f"Bing News RSS: {exc}")

        if ticker:
            try:
                found = self._yahoo_finance_rss(ticker, limit)["articles"]
                articles.extend(found)
                providers.append("Yahoo Finance RSS")
            except ProviderError as exc:
                errors.append(f"Yahoo Finance RSS: {exc}")

        if ticker and settings.finnhub_api_key:
            try:
                found = self._finnhub_company_news(ticker, limit)["articles"]
                articles.extend(found)
                providers.append("Finnhub Company News")
            except (ProviderError, ValueError, TypeError, KeyError, OverflowError) as exc:
                errors.append(f"Finnhub Company News: {exc}")

        if settings.alpha_vantage_api_key and ticker:
            try:
                found = self._alpha_vantage_news(ticker, limit)["articles"]
                articles.extend(found)
                providers.append("Alpha Vantage News Sentiment")
            except ProviderError as exc:
                errors.append(f"Alpha Vantage News Sentiment: {exc}")

        if settings.newsapi_api_key:
            try:
                found = self._newsapi(" OR ".join(search_queries[:3]) or query, limit)["articles"]
                articles.extend(found)
                providers.append("NewsAPI")
            except ProviderError as exc:
                errors.append(f"NewsAPI: {exc}")

        merged = self._deduplicate(articles, limit)
        if not merged and not errors:
            errors.append("All configured news indexes returned no matching articles.")

        result = {
            "articles": merged,
            "source": ", ".join(providers),
            "provider": ", ".join(providers),
            "providers": providers,
            "fallback_used": len(providers) > 0 and "GDELT DOC 2.0" not in providers,
            "partial_errors": errors,
            "coverage_note": "Aggregated indexed publisher results; not an exhaustive crawl of the entire internet.",
        }
        with self._cache_lock:
            self._cache[cache_key] = (time.time(), result)
        return result

    @staticmethod
    def _issuer_queries(query: str, ticker: str | None) -> list[str]:
        cleaned = re.sub(r'["“”]', " ", query)
        removable_terms = (
            r"analyze|analyse|latest|reported|revenue|profitability|balance sheet|"
            r"market trend|highlight|material risks|stock|share price"
        )
        cleaned = re.sub(
            rf"\b({removable_terms})\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = " ".join(cleaned.split()).strip(" .,;:-")
        variants = []
        if "south" in query.casefold():
            variants.extend(["South Indian Bank", '"South Indian Bank"'])
        if cleaned and len(cleaned) >= 3:
            variants.append(cleaned)
        if ticker:
            variants.append(ticker.replace(".NS", ""))
        return list(dict.fromkeys(item for item in variants if item))

    @staticmethod
    def _ticker_from_query(query: str) -> str | None:
        aliases = {
            "SOUTH INDIAN BANK": "SOUTHBANK.NS",
            "SOUTHBANK": "SOUTHBANK.NS",
            "APPLE": "AAPL", "MICROSOFT": "MSFT", "NVIDIA": "NVDA",
            "TESLA": "TSLA", "AMAZON": "AMZN", "GOOGLE": "GOOGL",
            "ALPHABET": "GOOGL", "META": "META",
        }
        for name, ticker in aliases.items():
            if re.search(rf"\b{name}\b", query, re.IGNORECASE):
                return ticker
        if re.search(r"\bSOUTH(?:BANK)?\b|SOUTH INDIAN BANK", query, re.IGNORECASE):
            return "SOUTHBANK.NS"
        tokens = re.findall(r"\b[A-Z]{2,5}\b", query)
        excluded = {
            "THE", "AND", "FOR", "WITH", "FROM", "WHAT", "HOW", "STOCK",
            "STOCKS", "NEWS", "LATEST", "ANALYZE", "ANALYSIS", "PRICE",
            "PERFORMANCE", "COMPANY", "SHARE", "SHARES", "ABOUT", "OF", "ON", "IS",
        }
        return next((token for token in tokens if token not in excluded), None)

    @staticmethod
    def _deduplicate(articles: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        for article in articles:
            url = (article.get("url") or "").split("?")[0].rstrip("/")
            title = " ".join((article.get("title") or "").casefold().split())
            key = url.casefold() or title
            if key and key not in unique:
                unique[key] = article
        return sorted(
            unique.values(),
            key=lambda item: item.get("publishedAt") or "",
            reverse=True,
        )[:limit]

    @staticmethod
    def _normalize_gdelt(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = []
        for article in articles:
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
        return normalized

    def _parse_rss(self, response: str, page_size: int, default_source: str) -> list[dict[str, Any]]:
        try:
            root = ET.fromstring(response)
        except ET.ParseError as exc:
            raise ProviderError(f"RSS provider returned invalid XML: {exc}") from exc
        articles = []
        for item in root.findall(".//item")[:page_size]:
            title = item.findtext("title") or "Untitled article"
            link = item.findtext("link")
            pub_date = item.findtext("pubDate")
            source_node = item.find("source")
            source_name = (
                source_node.text if source_node is not None and source_node.text
                else default_source
            )
            published = None
            if pub_date:
                try:
                    published = parsedate_to_datetime(pub_date).astimezone(UTC).isoformat()
                except (TypeError, ValueError, OverflowError):
                    published = pub_date
            if link:
                articles.append({
                    "title": title, "description": None, "publishedAt": published,
                    "url": link, "source": {"name": source_name},
                })
        if not articles:
            raise ProviderError("RSS provider returned no matching articles")
        return articles

    def _google_news_rss(self, query: str, page_size: int) -> dict[str, Any]:
        india_query = bool(re.search(r"\b(south indian bank|nse|bse|india)\b", query, re.IGNORECASE))
        region = {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"} if india_query else {
            "hl": "en-US", "gl": "US", "ceid": "US:en"
        }
        response = self.get_text(
            "https://news.google.com/rss/search",
            params={"q": query, **region},
            headers={"Accept": "application/rss+xml, application/xml, text/xml"},
            retries=0,
        )
        return {"articles": self._parse_rss(response, page_size, "Google News publisher"),
                "source": "Google News RSS", "provider": "Google News RSS"}

    def _bing_news_rss(self, query: str, page_size: int) -> dict[str, Any]:
        india_query = bool(re.search(r"\b(south indian bank|nse|bse|india)\b", query, re.IGNORECASE))
        response = self.get_text(
            "https://www.bing.com/news/search",
            params={"q": query, "format": "rss", "mkt": "en-IN" if india_query else "en-US"},
            headers={"Accept": "application/rss+xml, application/xml, text/xml"},
            retries=0,
        )
        return {"articles": self._parse_rss(response, page_size, "Bing News publisher"),
                "source": "Bing News RSS", "provider": "Bing News RSS"}

    def _yahoo_finance_rss(self, ticker: str, page_size: int) -> dict[str, Any]:
        response = self.get_text(
            "https://feeds.finance.yahoo.com/rss/2.0/headline",
            params={"s": ticker, "region": "US", "lang": "en-US"},
            headers={"Accept": "application/rss+xml, application/xml, text/xml"},
            retries=0,
        )
        return {"articles": self._parse_rss(response, page_size, "Yahoo Finance"),
                "source": "Yahoo Finance RSS", "provider": "Yahoo Finance RSS"}

    def _finnhub_company_news(self, ticker: str, page_size: int) -> dict[str, Any]:
        refresh_optional_api_keys()
        if not settings.finnhub_api_key:
            raise ProviderError("Optional FINNHUB_API_KEY is not configured")
        end = datetime.now(UTC).date()
        start = end - timedelta(days=30)
        data = self.get_json(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": start.isoformat(), "to": end.isoformat(),
                    "token": settings.finnhub_api_key},
            retries=0,
        )
        articles = [{
            "title": item.get("headline") or "Untitled article",
            "description": item.get("summary"),
            "publishedAt": datetime.fromtimestamp(int(item["datetime"]), UTC).isoformat()
                if item.get("datetime") else None,
            "url": item.get("url"),
            "source": {"name": item.get("source") or "Finnhub"},
        } for item in data if isinstance(item, dict) and item.get("url")]
        if not articles:
            raise ProviderError(f"Finnhub returned no company-news articles for {ticker}")
        return {"articles": articles[:page_size], "source": "Finnhub Company News",
                "provider": "Finnhub Company News"}

    def _alpha_vantage_news(self, ticker: str, page_size: int) -> dict[str, Any]:
        data = self.get_json(
            "https://www.alphavantage.co/query",
            params={"function": "NEWS_SENTIMENT", "tickers": ticker,
                    "limit": min(page_size, 50), "apikey": settings.alpha_vantage_api_key},
            retries=0,
        )
        if data.get("Note") or data.get("Information") or data.get("Error Message"):
            raise ProviderError(str(data.get("Note") or data.get("Information") or data.get("Error Message")))
        articles = [{
            "title": item.get("title") or "Untitled article",
            "description": item.get("summary"),
            "publishedAt": item.get("time_published"),
            "url": item.get("url"),
            "source": {"name": item.get("source") or "Alpha Vantage"},
        } for item in data.get("feed", []) if item.get("url")]
        if not articles:
            raise ProviderError(f"Alpha Vantage returned no news for {ticker}")
        return {"articles": articles, "provider": "Alpha Vantage News Sentiment"}

    def _newsapi(self, query: str, page_size: int) -> dict[str, Any]:
        data = self.get_json(
            "https://newsapi.org/v2/everything",
            params={"q": query, "sortBy": "publishedAt", "pageSize": page_size,
                    "language": "en"},
            headers={"X-Api-Key": settings.newsapi_api_key or ""},
            retries=0,
        )
        if data.get("status") != "ok":
            raise ProviderError(str(data.get("message") or "NewsAPI returned an error"))
        articles = [{
            "title": item.get("title") or "Untitled article",
            "description": item.get("description"),
            "publishedAt": item.get("publishedAt"),
            "url": item.get("url"),
            "source": {"name": (item.get("source") or {}).get("name") or "NewsAPI publisher"},
        } for item in data.get("articles", []) if item.get("url")]
        if not articles:
            raise ProviderError("NewsAPI returned no matching articles")
        return {"articles": articles, "source": "NewsAPI", "provider": "NewsAPI"}
