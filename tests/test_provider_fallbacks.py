from __future__ import annotations

import httpx
import pytest

from workbridge.providers import HttpProvider, NewsProvider, ProviderError


def test_public_get_requests_are_cached(monkeypatch):
    HttpProvider._cache.clear()
    HttpProvider._cooldowns.clear()
    HttpProvider._last_request.clear()
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, text="fresh data", request=httpx.Request("GET", url))

    monkeypatch.setattr("workbridge.providers.httpx.get", fake_get)
    provider = HttpProvider()
    assert provider.get_text("https://example.test/data") == "fresh data"
    assert provider.get_text("https://example.test/data") == "fresh data"
    assert len(calls) == 1


def test_news_uses_google_rss_when_gdelt_is_rate_limited(monkeypatch):
    provider = NewsProvider()

    def fail_gdelt(*args, **kwargs):
        raise ProviderError("api.gdeltproject.org returned HTTP 429")

    rss = """<?xml version="1.0"?><rss><channel><item>
      <title>Example Corp reports quarterly results</title>
      <link>https://publisher.example/article</link>
      <pubDate>Wed, 12 Nov 2026 10:00:00 GMT</pubDate>
      <source>Example Publisher</source>
    </item></channel></rss>"""
    monkeypatch.setattr(provider, "get_json", fail_gdelt)
    monkeypatch.setattr(provider, "get_text", lambda *args, **kwargs: rss)
    result = provider.search("Example Corp earnings", 5)
    assert result["source"] == "Google News RSS"
    assert result["articles"][0]["title"] == "Example Corp reports quarterly results"
    assert result["articles"][0]["url"] == "https://publisher.example/article"


def test_news_reports_failure_only_when_both_public_sources_fail(monkeypatch):
    provider = NewsProvider()
    monkeypatch.setattr(
        provider, "get_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("GDELT HTTP 429")),
    )
    monkeypatch.setattr(
        provider, "get_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProviderError("Google News HTTP 429")),
    )
    result = provider.search("Example Corp", 5)

    # News search returns a structured partial-failure result so the UI can
    # display provider diagnostics instead of turning a missing news feed
    # into an unhandled research-run exception.
    assert result["articles"] == []
    assert result["partial_errors"]
    assert "GDELT" in " ".join(result["partial_errors"])
    assert "Google News RSS" in " ".join(result["partial_errors"])
