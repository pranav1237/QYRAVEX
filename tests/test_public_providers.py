from workbridge.providers import MacroProvider, MarketProvider, NewsProvider, ProviderError


def test_market_provider_falls_back_to_stooq_when_yahoo_is_rate_limited(monkeypatch):
    provider = MarketProvider()

    def fail_yahoo(*args, **kwargs):
        raise ProviderError("HTTP 429 Too Many Requests")

    monkeypatch.setattr(provider, "get_json", fail_yahoo)
    monkeypatch.setattr(
        provider,
        "get_text",
        lambda *args, **kwargs: (
            "Date,Open,High,Low,Close,Volume\n"
            "2026-01-02,100,105,99,104,1000\n"
            "2026-01-05,104,108,103,107,1200\n"
        ),
    )

    result = provider.price_history("MSFT", "1y")
    row = result["chart"]["result"][0]
    assert row["meta"]["dataProvider"] == "Stooq"
    assert row["indicators"]["quote"][0]["close"] == [104.0, 107.0]



def test_ambiguous_south_query_searches_south_indian_bank_issuer(monkeypatch):
    provider = MarketProvider()
    calls = []

    def fake_json(url, **kwargs):
        calls.append(kwargs.get("params", {}).get("q"))
        return {"quotes": [{
            "symbol": "SOUTHBANK.NS",
            "shortname": "South Indian Bank Limited",
            "exchDisp": "NSE",
            "exch": "NSI",
            "quoteType": "EQUITY",
            "currency": "INR",
        }]}

    monkeypatch.setattr(provider, "get_json", fake_json)
    matches = provider.search_symbols("SOUTH")
    assert calls == ["South Indian Bank"]
    assert matches[0]["symbol"] == "SOUTHBANK.NS"
    assert matches[0]["currency"] == "INR"


def test_market_symbol_search_returns_exchange_and_source_metadata(monkeypatch):
    provider = MarketProvider()
    monkeypatch.setattr(provider, "get_json", lambda *args, **kwargs: {
        "quotes": [{
            "symbol": "SOUTHBANK.NS",
            "shortname": "South Indian Bank Limited",
            "exchDisp": "NSE",
            "exch": "NSI",
            "quoteType": "EQUITY",
            "currency": "INR",
        }]
    })
    matches = provider.search_symbols("South Indian Bank")
    assert matches[0]["symbol"] == "SOUTHBANK.NS"
    assert matches[0]["exchange"] == "NSE"
    assert matches[0]["currency"] == "INR"
    assert matches[0]["source_url"].endswith("/SOUTHBANK.NS")


def test_market_provider_resolves_exchange_qualified_listing_after_bad_symbol(monkeypatch):
    provider = MarketProvider()
    calls = []

    def fake_json(url, **kwargs):
        calls.append(url)
        if url.endswith("/v8/finance/chart/SOUTH"):
            raise ProviderError("404 Not Found")
        if "/v1/finance/search" in url:
            return {"quotes": [{
                "symbol": "SOUTHBANK.NS", "shortname": "South Indian Bank",
                "exchDisp": "NSE", "exch": "NSI", "quoteType": "EQUITY",
            }]}
        return {"chart": {"result": [{
            "timestamp": [1794432000, 1794518400],
            "meta": {"symbol": "SOUTHBANK.NS", "currency": "INR"},
            "indicators": {"quote": [{"close": [25.0, 26.0]}]},
        }]}}
    monkeypatch.setattr(provider, "get_json", fake_json)
    result = provider.price_history("SOUTH", "1mo")
    row = result["chart"]["result"][0]
    assert row["meta"]["symbol"] == "SOUTHBANK.NS"
    assert row["meta"]["symbolSearch"]["exchange"] == "NSE"
    assert row["indicators"]["quote"][0]["close"] == [25.0, 26.0]

def test_fred_public_csv_does_not_require_api_key(monkeypatch):
    provider = MacroProvider()
    monkeypatch.setattr(
        provider,
        "get_text",
        lambda *args, **kwargs: (
            "observation_date,CPIAUCSL\n"
            "2026-01-01,321.5\n"
            "2026-02-01,322.1\n"
        ),
    )

    result = provider.series("CPIAUCSL", 2)
    assert result["observations"][-1] == {"date": "2026-02-01", "value": "322.1"}


def test_gdelt_news_is_normalized_without_newsapi_key():
    articles = NewsProvider._normalize_gdelt([{
        "title": "Company reports quarterly results",
        "url": "https://example.com/results",
        "domain": "example.com",
        "seendate": "20260601T120000Z",
    }])
    assert articles[0]["title"] == "Company reports quarterly results"
    assert articles[0]["publishedAt"] == "2026-06-01T12:00:00Z"
    assert articles[0]["source"]["name"] == "example.com"
    assert articles[0]["url"] == "https://example.com/results"


def test_sec_evidence_links_open_human_readable_company_and_filing_pages():
    from workbridge.tools import _sec_company_url, _sec_filing_url

    assert _sec_company_url("0000789019") == (
        "https://www.sec.gov/edgar/browse/?CIK=789019&owner=exclude"
    )
    assert _sec_filing_url("0000789019", "0000950170-26-000123") == (
        "https://www.sec.gov/Archives/edgar/data/789019/000095017026000123/"
    )
    assert _sec_filing_url("0000789019", None) == _sec_company_url("0000789019")
    assert _sec_filing_url("0000789019", "invalid") == _sec_company_url("0000789019")


def test_finnhub_company_news_is_normalized(monkeypatch):
    from types import SimpleNamespace

    import workbridge.providers as providers_module

    monkeypatch.setattr(
        providers_module,
        "settings",
        SimpleNamespace(finnhub_api_key="test-token", timeout_seconds=20),
    )
    provider = NewsProvider()
    monkeypatch.setattr(
        provider,
        "get_json",
        lambda *args, **kwargs: [{
            "headline": "Example company expands cloud business",
            "summary": "Company news summary",
            "datetime": 1794484800,
            "url": "https://example.com/company-news",
            "source": "Example Wire",
        }],
    )

    result = provider._finnhub_company_news("MSFT", 10)
    assert result["provider"] == "Finnhub Company News"
    assert result["articles"][0]["title"] == "Example company expands cloud business"
    assert result["articles"][0]["url"] == "https://example.com/company-news"
    assert result["articles"][0]["source"]["name"] == "Example Wire"

def test_tool_registry_market_evidence_does_not_shadow_url_quote_function():
    from workbridge.tools import ToolRegistry

    class FakeMarket:
        def price_history(self, symbol, period):
            return {"chart": {"result": [{
                "meta": {"symbol": "MSFT", "currency": "USD", "dataProvider": "Yahoo Finance"},
                "timestamp": [1794432000, 1794518400],
                "indicators": {"quote": [{"close": [100.0, 101.0]}]},
            }]}}

    registry = ToolRegistry.__new__(ToolRegistry)
    registry.market = FakeMarket()
    result = registry.price_history("MSFT", "1mo")
    assert result.success
    assert result.data["source_url"] == "https://finance.yahoo.com/quote/MSFT"
    assert result.evidence[0].source_url == "https://finance.yahoo.com/quote/MSFT"




def test_news_provider_uses_bing_rss_after_gdelt_and_google_fail(monkeypatch):
    provider = NewsProvider()
    monkeypatch.setattr(provider, "get_json", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("HTTP 429")))
    monkeypatch.setattr(provider, "_google_news_rss", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_yahoo_finance_rss", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_finnhub_company_news", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_alpha_vantage_news", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_newsapi", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_bing_news_rss", lambda query, limit: {
        "articles": [{
            "title": "South Indian Bank announces quarterly results",
            "url": "https://example.com/results",
            "publishedAt": "2026-11-13T10:00:00Z",
            "source": {"name": "Example News"},
        }]
    })
    result = provider.search("SouthBank latest reported revenue", 10)
    assert result["articles"][0]["title"].startswith("South Indian Bank")
    assert "Bing News RSS" in result["providers"]


def test_news_provider_returns_diagnostic_empty_result_instead_of_raising(monkeypatch):
    provider = NewsProvider()
    monkeypatch.setattr(provider, "get_json", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("HTTP 429")))
    monkeypatch.setattr(provider, "_google_news_rss", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_bing_news_rss", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_yahoo_finance_rss", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_finnhub_company_news", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_alpha_vantage_news", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    monkeypatch.setattr(provider, "_newsapi", lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")))
    result = provider.search("SouthBank latest filings no match", 10)
    assert result["articles"] == []
    assert result["partial_errors"]
    assert "not evidence that the issuer has no recent news" not in result.get("coverage_note", "")


def test_news_provider_builds_broad_south_indian_bank_queries():
    assert NewsProvider._ticker_from_query("SouthBank latest reported revenue") == "SOUTHBANK.NS"
    queries = NewsProvider._issuer_queries("SouthBank latest reported revenue and profitability", "SOUTHBANK.NS")
    assert "South Indian Bank" in queries
    assert "SOUTHBANK" in queries


def test_alpha_vantage_news_is_normalized(monkeypatch):
    from types import SimpleNamespace

    import workbridge.providers as providers_module

    monkeypatch.setattr(
        providers_module, "settings",
        SimpleNamespace(alpha_vantage_api_key="test-token", timeout_seconds=5),
    )
    provider = NewsProvider()
    monkeypatch.setattr(provider, "get_json", lambda *args, **kwargs: {
        "feed": [{
            "title": "South Indian Bank reports quarterly results",
            "summary": "Revenue and profit update",
            "time_published": "20261113T120000",
            "url": "https://example.com/southbank-results",
            "source": "Example Finance",
        }]
    })
    result = provider._alpha_vantage_news("SOUTHBANK.NS", 10)
    assert result["articles"][0]["title"].startswith("South Indian Bank")
    assert result["articles"][0]["source"]["name"] == "Example Finance"



def test_ai_research_provider_calls_all_configured_model_apis(monkeypatch):
    from types import SimpleNamespace

    import workbridge.providers as providers_module

    monkeypatch.setattr(
        providers_module, "settings",
        SimpleNamespace(
            openai_api_key="openai-test", gemini_api_key="gemini-test",
            anthropic_api_key="anthropic-test",
        ),
    )
    monkeypatch.setattr(providers_module, "refresh_optional_api_keys", lambda: None)

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_post(url, **kwargs):
        if "api.openai.com" in url:
            return FakeResponse({"choices": [{"message": {"content": "OpenAI review"}}]})
        if "generativelanguage.googleapis.com" in url:
            return FakeResponse({"candidates": [{"content": {"parts": [{"text": "Gemini review"}]}}]})
        return FakeResponse({"content": [{"text": "Claude review"}]})

    monkeypatch.setattr(providers_module.httpx, "post", fake_post)
    result = providers_module.AIResearchProvider().analyze(
        company="South Indian Bank", symbol="SOUTHBANK.NS", horizon=20,
        market_facts={"latest_close": 25.0}, articles=[],
    )
    assert result["successful_providers"] == ["OpenAI", "Google Gemini", "Anthropic Claude"]
    assert len(result["analyses"]) == 3

def test_news_provider_uses_google_rss_when_gdelt_raises_raw_http_429(monkeypatch):
    import httpx

    provider = NewsProvider()
    request = httpx.Request("GET", "https://api.gdeltproject.org/api/v2/doc/doc")
    response = httpx.Response(429, request=request)
    error = httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)

    def fail_gdelt(*args, **kwargs):
        raise error

    article = {
        "title": "South Indian Bank quarterly results",
        "url": "https://example.com/southbank-results",
        "publishedAt": "2026-11-13T10:00:00Z",
        "source": {"name": "Example News"},
    }
    monkeypatch.setattr(provider, "get_json", fail_gdelt)
    monkeypatch.setattr(
        provider, "_google_news_rss",
        lambda query, limit: {"articles": [article], "provider": "Google News RSS"},
    )
    monkeypatch.setattr(
        provider, "_yahoo_finance_rss",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("no articles")),
    )

    result = provider.search("SouthBank latest results regression-raw-429", 10)

    assert result["articles"]
    assert result["articles"][0]["title"] == article["title"]
    assert "Google News RSS" in result["providers"]
    assert any("GDELT: HTTPStatusError" in item for item in result["partial_errors"])

