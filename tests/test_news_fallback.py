from workbridge.providers import NewsProvider, ProviderError


def test_news_uses_google_rss_when_gdelt_is_rate_limited(monkeypatch):
    provider = NewsProvider()
    calls = {"rss": 0}

    def fail_gdelt(*args, **kwargs):
        raise ProviderError("HTTP 429 Too Many Requests")

    rss = """<?xml version="1.0"?>
    <rss><channel><item>
      <title>Example company reports quarterly results</title>
      <link>https://example.com/news/quarterly-results</link>
      <pubDate>Thu, 12 Nov 2026 10:00:00 GMT</pubDate>
      <source>Example News</source>
    </item></channel></rss>"""

    def google_rss(*args, **kwargs):
        calls["rss"] += 1
        return rss

    monkeypatch.setattr(provider, "get_json", fail_gdelt)
    monkeypatch.setattr(provider, "get_text", google_rss)

    result = provider.search("Example company stock", page_size=5)

    assert result["provider"] == "Google News RSS"
    assert result["fallback_used"] is True
    assert result["articles"][0]["title"] == "Example company reports quarterly results"
    assert result["articles"][0]["url"] == "https://example.com/news/quarterly-results"


def test_news_search_caches_recent_fallback_response(monkeypatch):
    provider = NewsProvider()
    calls = {"rss": 0}

    def fail_gdelt(*args, **kwargs):
        raise ProviderError("HTTP 429 Too Many Requests")

    rss = """<rss><channel><item>
      <title>Cached market headline</title>
      <link>https://example.com/cached</link>
    </item></channel></rss>"""

    def google_rss(*args, **kwargs):
        calls["rss"] += 1
        return rss

    monkeypatch.setattr(provider, "get_json", fail_gdelt)
    monkeypatch.setattr(provider, "get_text", google_rss)

    first = provider.search("unique cache test query")
    second = provider.search("unique cache test query")

    assert first["provider"] == "Google News RSS"
    assert second["cached"] is True
    assert calls["rss"] == 1



def test_news_aggregates_independent_public_sources_and_deduplicates(monkeypatch):
    provider = NewsProvider()
    rss = """<rss><channel><item>
      <title>Microsoft shares rise after earnings</title>
      <link>https://publisher.example/microsoft-earnings</link>
      <pubDate>Thu, 12 Nov 2026 10:00:00 GMT</pubDate>
      <source>Publisher</source>
    </item></channel></rss>"""

    def gdelt(*args, **kwargs):
        return {"articles": [{
            "title": "Microsoft shares rise after earnings",
            "url": "https://publisher.example/microsoft-earnings",
            "domain": "publisher.example",
            "seendate": "20261112T100000Z",
        }, {
            "title": "Microsoft announces AI expansion",
            "url": "https://publisher.example/microsoft-ai",
            "domain": "publisher.example",
            "seendate": "20261112T090000Z",
        }]}

    monkeypatch.setattr(provider, "get_json", gdelt)
    monkeypatch.setattr(provider, "get_text", lambda *args, **kwargs: rss)
    result = provider.search("Microsoft", page_size=20)

    assert "GDELT DOC 2.0" in result["providers"]
    assert "Google News RSS" in result["providers"]
    assert "Yahoo Finance RSS" in result["providers"]
    assert len(result["articles"]) == 2
    assert result["articles"][0]["url"].startswith("https://")


def test_ticker_detection_does_not_treat_sentence_initials_as_tickers():
    assert NewsProvider._ticker_from_query("Example company stock news") is None
    assert NewsProvider._ticker_from_query("Analyze MSFT stock") == "MSFT"
    assert NewsProvider._ticker_from_query("Latest news about Apple") == "AAPL"
