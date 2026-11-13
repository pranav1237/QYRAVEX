"""Typed tool registry: 12+ distinct research tools with provenance."""
from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote as url_quote

from .config import refresh_optional_api_keys, settings
from .memory import MemoryStore
from .models import Evidence, ToolResult
from .providers import MacroProvider, MarketProvider, NewsProvider, ProviderError, SecProvider

ToolFn = Callable[..., ToolResult]


def _sec_company_url(cik: str | int) -> str:
    """Return the human-readable SEC filing page, not the raw JSON API."""
    return f"https://www.sec.gov/edgar/browse/?CIK={int(cik)}&owner=exclude"


def _sec_filing_url(cik: str | int, accession_number: str | None) -> str:
    """Link evidence to the exact SEC filing that reported the observation."""
    if not accession_number:
        return _sec_company_url(cik)
    accession = str(accession_number).replace("-", "")
    if not accession.isdigit():
        return _sec_company_url(cik)
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/"


def _evidence(tool: str, statement: str, value: Any, source: str, url: str | None = None,
              entity: str | None = None, period: str | None = None, unit: str | None = None,
              confidence: float = .85) -> Evidence:
    raw = f"{tool}|{statement}|{source}|{entity}|{period}"
    return Evidence(id=hashlib.sha256(raw.encode()).hexdigest()[:16], statement=statement,
                    value=value, source=source, source_url=url, entity=entity, period=period,
                    unit=unit, confidence=confidence)


class ToolRegistry:
    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory
        self.sec, self.market, self.macro, self.news = SecProvider(), MarketProvider(), MacroProvider(), NewsProvider()
        self.tools: dict[str, tuple[str, ToolFn]] = {
            "resolve_ticker": ("Resolve a public-company ticker to SEC CIK and legal name.", self.resolve_ticker),
            "sec_company_facts": ("Retrieve reported XBRL company facts from SEC EDGAR.", self.sec_company_facts),
            "sec_filings": ("Retrieve recent SEC filing metadata.", self.sec_filings),
            "financial_snapshot": ("Extract reported income statement, balance sheet and cash-flow facts.", self.financial_snapshot),
            "price_history": ("Retrieve daily adjusted market-price history.", self.price_history),
            "technical_summary": ("Calculate return, volatility and drawdown from price history.", self.technical_summary),
            "company_profile": ("Retrieve company profile, sector and market capitalization.", self.company_profile),
            "macro_series": ("Retrieve a FRED macroeconomic time series.", self.macro_series),
            "news_search": ("Search recent news headlines and metadata.", self.news_search),
            "memory_search": ("Search durable evidence from prior research runs.", self.memory_search),
            "memory_write": ("Persist evidence into durable memory.", self.memory_write),
            "calculate_financial_ratio": ("Calculate transparent financial ratios from supplied values.", self.calculate_financial_ratio),
            "compare_entities": ("Compare evidence coverage and values across entities.", self.compare_entities),
            "source_health": ("Check which optional provider integrations are configured.", self.source_health),
        }

    def descriptions(self) -> dict[str, str]:
        return {name: description for name, (description, _) in self.tools.items()}

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        started = time.perf_counter()
        if name not in self.tools:
            return ToolResult(tool=name, success=False, error="Unknown tool")
        try:
            result = self.tools[name][1](**args)
            result.latency_ms = (time.perf_counter() - started) * 1000
            return result
        except Exception as exc:  # tool boundary: isolate provider and parsing failures
            return ToolResult(tool=name, success=False, error=f"{type(exc).__name__}: {exc}",
                              latency_ms=(time.perf_counter() - started) * 1000)

    def resolve_ticker(self, ticker: str) -> ToolResult:
        rows = self.sec.ticker_map()
        row = rows.get(ticker.upper())
        if not row:
            return ToolResult(tool="resolve_ticker", success=False, error=f"Ticker not found in SEC map: {ticker}")
        data = {"ticker": ticker.upper(), "cik": str(row["cik_str"]), "name": row["title"]}
        ev = _evidence("resolve_ticker", f"{ticker.upper()} maps to {row['title']} (CIK {row['cik_str']})",
                       data, "SEC company tickers", _sec_company_url(row["cik_str"]), row["title"])
        return ToolResult(tool="resolve_ticker", success=True, data=data, evidence=[ev])

    def sec_company_facts(self, cik: str) -> ToolResult:
        data = self.sec.company_facts(cik)
        facts = data.get("facts", {})
        summary = {"entityName": data.get("entityName"), "cik": data.get("cik"), "taxonomy_count": len(facts)}
        ev = [_evidence("sec_company_facts", f"SEC company facts retrieved for {data.get('entityName')}",
                        summary, "SEC EDGAR companyfacts", _sec_company_url(cik),
                        data.get("entityName"))]
        return ToolResult(tool="sec_company_facts", success=True, data=data, evidence=ev)

    def sec_filings(self, cik: str) -> ToolResult:
        data = self.sec.submissions(cik)
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        filings = [{"form": forms[i], "filingDate": recent.get("filingDate", [])[i],
                    "accessionNumber": recent.get("accessionNumber", [])[i],
                    "primaryDocument": recent.get("primaryDocument", [])[i]}
                   for i in range(min(12, len(forms)))]
        ev = [_evidence("sec_filings", f"Retrieved {len(filings)} recent SEC filings for {data.get('name')}",
                        filings, "SEC EDGAR submissions", _sec_company_url(cik),
                        data.get("name"))]
        return ToolResult(tool="sec_filings", success=True, data=filings, evidence=ev)

    def financial_snapshot(self, cik: str) -> ToolResult:
        data = self.sec.company_facts(cik)
        us = data.get("facts", {}).get("us-gaap", {})
        candidates = {
            "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
            "gross_profit": ["GrossProfit"],
            "operating_income": ["OperatingIncomeLoss"],
            "net_income": ["NetIncomeLoss"],
            "diluted_eps": ["EarningsPerShareDiluted"],
            "total_assets": ["Assets"],
            "current_assets": ["AssetsCurrent"],
            "total_liabilities": ["Liabilities"],
            "current_liabilities": ["LiabilitiesCurrent"],
            "stockholders_equity": ["StockholdersEquity"],
            "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
            "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
            "capital_expenditures": ["PaymentsToAcquirePropertyPlantAndEquipment"],
        }
        snapshot: dict[str, Any] = {}
        evidence: list[Evidence] = []
        entity = data.get("entityName")
        for key, tags in candidates.items():
            for tag in tags:
                fact = us.get(tag)
                if not fact:
                    continue
                units = fact.get("units", {})
                unit_name = next(iter(units), None)
                entries = units.get(unit_name, []) if unit_name else []
                if not entries:
                    continue
                # Prefer the latest filed observation, retaining its actual period and form.
                entry = sorted(
                    entries,
                    key=lambda x: (x.get("filed", ""), x.get("end", "")),
                    reverse=True,
                )[0]
                snapshot[key] = {"value": entry.get("val"), "unit": unit_name,
                                 "period_end": entry.get("end"), "filed": entry.get("filed"),
                                 "form": entry.get("form"), "accession_number": entry.get("accn"), "tag": tag}
                evidence.append(_evidence("financial_snapshot",
                    f"{entity} {key.replace('_', ' ')} reported as {entry.get('val')} {unit_name} for period ending {entry.get('end')}",
                    entry.get("val"), "SEC EDGAR XBRL", _sec_filing_url(cik, entry.get("accn")),
                    entity, entry.get("end"), unit_name, .92))
                break
        return ToolResult(tool="financial_snapshot", success=bool(snapshot), data=snapshot,
                          evidence=evidence, error=None if snapshot else "No supported US-GAAP tags found")

    def price_history(self, symbol: str, period: str = "1y") -> ToolResult:
        data = self.market.price_history(symbol, period)
        result = data.get("chart", {}).get("result") or []
        if not result:
            raise ProviderError("Market data provider returned no chart result")
        row = result[0]
        quote = row.get("indicators", {}).get("quote", [{}])[0]
        closes = [x for x in quote.get("close", []) if x is not None]
        timestamps = row.get("timestamp", [])
        records = [{"timestamp": timestamps[i], "close": quote["close"][i]}
                   for i in range(min(len(timestamps), len(quote.get("close", []))))
                   if quote["close"][i] is not None]
        meta = row.get("meta", {})
        resolved_symbol = meta.get("symbol") or symbol.upper()
        company = meta.get("longName") or meta.get("shortName")
        exchange = meta.get("fullExchangeName") or meta.get("exchangeName")
        provider = meta.get("dataProvider", "Yahoo Finance")
        source_url = (
            f"https://finance.yahoo.com/quote/{url_quote(resolved_symbol)}"
            if provider == "Yahoo Finance"
            else f"https://stooq.com/q/?s={resolved_symbol.lower()}.us"
        )
        ev = _evidence(
            "price_history",
            f"Retrieved {len(records)} daily closes for {resolved_symbol} from {provider}"
            + (f" ({company}, {exchange})" if company or exchange else ""),
            records[-5:],
            provider + " daily price history",
            source_url,
            company or resolved_symbol,
            period,
            meta.get("currency", "USD"),
        )
        return ToolResult(tool="price_history", success=True, data={"symbol": resolved_symbol,
                          "company": company, "exchange": exchange,
                          "currency": meta.get("currency"),
                          "provider": provider, "source_url": source_url,
                          "closes": closes, "records": records}, evidence=[ev])

    def technical_summary(self, symbol: str, period: str = "1y") -> ToolResult:
        raw = self.price_history(symbol, period)
        if not raw.success:
            return raw
        closes = raw.data["closes"]
        if len(closes) < 2:
            return ToolResult(tool="technical_summary", success=False, error="Insufficient price observations")
        returns = [closes[i] / closes[i-1] - 1 for i in range(1, len(closes)) if closes[i-1]]
        peak, max_dd = closes[0], 0.0
        for price in closes:
            peak = max(peak, price)
            max_dd = min(max_dd, price / peak - 1)
        volatility = (sum((x - sum(returns)/len(returns))**2 for x in returns) /
                      max(1, len(returns)-1)) ** .5 * math.sqrt(252)
        data = {"observations": len(closes), "period_return": closes[-1]/closes[0]-1,
                "annualized_volatility": volatility, "max_drawdown": max_dd,
                "latest_close": closes[-1]}
        provider = raw.data.get("provider", "Yahoo Finance")
        resolved_symbol = raw.data.get("symbol", symbol.upper())
        source_url = raw.data.get("source_url") or (
            f"https://stooq.com/q/?s={resolved_symbol.lower()}.us"
            if provider == "Stooq"
            else f"https://finance.yahoo.com/quote/{url_quote(resolved_symbol)}"
        )
        ev = _evidence("technical_summary", f"{resolved_symbol} price return over {period}: {data['period_return']:.2%}",
                       data, f"Calculated from {provider} daily close observations",
                       source_url, raw.data.get("company") or resolved_symbol, period)
        return ToolResult(tool="technical_summary", success=True, data=data, evidence=[ev])

    def company_profile(self, symbol: str) -> ToolResult:
        data = self.market.profile(symbol)
        ev = _evidence("company_profile", f"Profile retrieved for {symbol.upper()}", data,
                       "Finnhub company profile", "https://finnhub.io", symbol.upper())
        return ToolResult(tool="company_profile", success=True, data=data, evidence=[ev])

    def macro_series(self, series_id: str, limit: int = 24) -> ToolResult:
        data = self.macro.series(series_id, limit)
        observations = data.get("observations", [])
        ev = _evidence("macro_series", f"Retrieved {len(observations)} observations for FRED series {series_id}",
                       observations[:5], "FRED public observations",
                       f"https://fred.stlouisfed.org/series/{series_id}", series_id)
        return ToolResult(tool="macro_series", success=True, data=observations, evidence=[ev])

    def news_search(self, query: str, page_size: int = 10) -> ToolResult:
        data = self.news.search(query, page_size)
        articles = data.get("articles", [])
        evidence = [_evidence("news_search", article.get("title", "Untitled article"),
                    {"description": article.get("description"), "publishedAt": article.get("publishedAt"),
                     "url": article.get("url"), "source": article.get("source", {}).get("name")},
                    article.get("source", {}).get("name", data.get("provider", "News publisher")),
                    article.get("url"), period=article.get("publishedAt")) for article in articles]
        warnings = []
        if data.get("fallback_used"):
            warnings.append("GDELT was unavailable; results were collected from other live news indexes.")
        if data.get("partial_errors"):
            warnings.append("Some news providers were unavailable: " + "; ".join(data["partial_errors"]))
        if data.get("coverage_note"):
            warnings.append(data["coverage_note"])
        if data.get("cached"):
            warnings.append("Showing a recent live-news response cached for up to three minutes.")
        return ToolResult(tool="news_search", success=True, data={
            "articles": articles, "provider": data.get("provider", "News provider"),
            "providers": data.get("providers", []), "coverage_note": data.get("coverage_note"),
        }, evidence=evidence, warnings=warnings)

    def memory_search(self, query: str, limit: int = 8) -> ToolResult:
        items = self.memory.search(query, limit)
        return ToolResult(tool="memory_search", success=True, data=[x.model_dump(mode="json") for x in items],
                          evidence=[], cached=True, warnings=["Historical memory is not counted as live evidence."])

    def memory_write(self, evidence: list[dict[str, Any]]) -> ToolResult:
        items = [Evidence.model_validate(item) for item in evidence]
        count = self.memory.remember_evidence(items)
        return ToolResult(tool="memory_write", success=True, data={"stored": count})

    def calculate_financial_ratio(self, numerator: float, denominator: float,
                                  ratio: str = "ratio") -> ToolResult:
        if denominator == 0:
            return ToolResult(tool="calculate_financial_ratio", success=False, error="Denominator cannot be zero")
        value = numerator / denominator
        ev = _evidence("calculate_financial_ratio", f"{ratio} = {numerator} / {denominator} = {value:.4f}",
                       value, "Deterministic calculation", confidence=1.0)
        return ToolResult(tool="calculate_financial_ratio", success=True,
                          data={"ratio": ratio, "value": value}, evidence=[ev])

    def compare_entities(self, entities: list[str], evidence: list[dict[str, Any]]) -> ToolResult:
        grouped: dict[str, list[dict[str, Any]]] = {name: [] for name in entities}
        for item in evidence:
            if item.get("entity") in grouped:
                grouped[item["entity"]].append(item)
        return ToolResult(tool="compare_entities", success=True, data=grouped)

    def source_health(self) -> ToolResult:
        refresh_optional_api_keys()
        data = {
            "sec_edgar": True,
            "market_data_yahoo_stooq": True,
            "fred_public_data": True,
            "gdelt_public_news": True,
            "google_news_rss": True,
            "yahoo_finance_rss": True,
            "newsapi_optional": bool(settings.newsapi_api_key),
            "finnhub_optional": bool(settings.finnhub_api_key),
        }
        return ToolResult(tool="source_health", success=True, data=data)
