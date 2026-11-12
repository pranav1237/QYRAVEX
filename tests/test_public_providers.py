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


def test_gdelt_news_is_normalized_without_newsapi_key(monkeypatch):
    NewsProvider._cache.clear()
    provider = NewsProvider()
    monkeypatch.setattr(
        provider,
        "get_json",
        lambda *args, **kwargs: {
            "articles": [{
                "title": "Company reports quarterly results",
                "url": "https://example.com/results",
                "domain": "example.com",
                "seendate": "20260601T120000Z",
            }]
        },
    )

    result = provider.search("MSFT earnings", 5)
    article = next(item for item in result["articles"] if item["title"] == "Company reports quarterly results")
    assert article["publishedAt"] == "2026-06-01T12:00:00Z"
    assert article["source"]["name"] == "example.com"


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
