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
