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
    article = result["articles"][0]
    assert article["title"] == "Company reports quarterly results"
    assert article["publishedAt"] == "2026-06-01T12:00:00Z"
    assert article["source"]["name"] == "example.com"
