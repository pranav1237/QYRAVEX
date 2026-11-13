# ruff: noqa: I001
from fastapi.testclient import TestClient

from workbridge.web import app


client = TestClient(app)


def test_dashboard_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "QYRAVEX" in response.text
    assert "Research desk" in response.text


def test_dashboard_assets_are_served():
    response = client.get("/app.js")
    assert response.status_code == 200
    assert "runResearch" in response.text
    assert "loadMarketForecast" in response.text
    assert "drawForecastChart" in response.text

    page = client.get("/")
    assert 'id="stock-load"' in page.text
    assert 'id="stock-forecast-chart"' in page.text
    assert 'id="stock-candidates"' in page.text


def test_benchmark_api_returns_all_challenges():
    response = client.get("/api/benchmarks")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 8
    assert payload["passed"] == 8



def test_market_chart_api_returns_timestamped_price_observations(monkeypatch):
    def fake_history(self, symbol, period):
        return {"chart": {"result": [{
            "meta": {"currency": "USD", "dataProvider": "Yahoo Finance"},
            "timestamp": [1794432000, 1794518400, 1794604800],
            "indicators": {"quote": [{"close": [100.0, 102.0, 101.5]}]},
        }]}}
    monkeypatch.setattr("workbridge.web.MarketProvider.price_history", fake_history)
    response = client.get("/api/market/MSFT?period=1y")
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "MSFT"
    assert payload["provider"] == "Yahoo Finance"
    assert len(payload["points"]) == 3
    assert payload["latest"]["close"] == 101.5



def test_market_symbol_search_api_returns_verifiable_candidates(monkeypatch):
    monkeypatch.setattr(
        "workbridge.web.MarketProvider.search_symbols",
        lambda self, query: [{
            "symbol": "SOUTHBANK.NS",
            "name": "South Indian Bank Limited",
            "exchange": "NSE",
            "quote_type": "EQUITY",
            "source": "Yahoo Finance symbol search",
            "source_url": "https://finance.yahoo.com/quote/SOUTHBANK.NS",
        }],
    )
    response = client.get("/api/market/search?q=South%20Indian%20Bank")
    assert response.status_code == 200
    payload = response.json()
    assert payload["matches"][0]["symbol"] == "SOUTHBANK.NS"
    assert payload["matches"][0]["exchange"] == "NSE"
    assert payload["matches"][0]["source_url"].startswith("https://finance.yahoo.com/")


def test_market_forecast_returns_scenarios_and_linked_news(monkeypatch):
    closes = [100.0 + index * 0.35 + (index % 5) * 0.08 for index in range(80)]
    timestamps = [1790000000 + index * 86400 for index in range(len(closes))]
    monkeypatch.setattr(
        "workbridge.web.MarketProvider.price_history",
        lambda self, symbol, period: {"chart": {"result": [{
            "meta": {"symbol": "MSFT", "currency": "USD", "dataProvider": "Yahoo Finance",
                     "longName": "Microsoft Corporation", "fullExchangeName": "Nasdaq"},
            "timestamp": timestamps,
            "indicators": {"quote": [{"close": closes}]},
        }]}},
    )
    monkeypatch.setattr(
        "workbridge.web.NewsProvider.search",
        lambda self, query, page_size: {
            "articles": [{
                "title": "Microsoft reports strong growth and profit",
                "publishedAt": "2026-11-12T12:00:00Z",
                "url": "https://example.com/microsoft-results",
                "source": {"name": "Example Financial News"},
            }],
            "providers": ["GDELT DOC 2.0"],
            "coverage_note": "Indexed headlines only.",
        },
    )
    response = client.get("/api/market/MSFT/forecast?horizon=20")
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "MSFT"
    assert payload["horizon_trading_days"] == 20
    assert payload["scenarios"]["bear"] < payload["scenarios"]["base"] < payload["scenarios"]["bull"]
    assert payload["news"]["article_count"] == 1
    assert payload["sources"][1]["url"] == "https://example.com/microsoft-results"
    assert "not a guarantee" in payload["limitations"][0]


def test_market_forecast_rejects_unsupported_horizon():
    response = client.get("/api/market/MSFT/forecast?horizon=17")
    assert response.status_code == 422

def test_market_chart_api_rejects_invalid_period():
    response = client.get("/api/market/MSFT?period=intraday")
    assert response.status_code == 422
