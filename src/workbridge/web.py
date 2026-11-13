"""Browser API and static dashboard for QYRAVEX."""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import ResearchAgent
from .benchmarks import run_challenges
from .config import settings
from .memory import MemoryStore
from .providers import MarketProvider, NewsProvider, ProviderError
from .synthesis import synthesize
from .tools import ToolRegistry

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="QYRAVEX",
    version="0.2.0",
    description="QYRAVEX autonomous, evidence-aware financial research workspace",
)


class ResearchRequest(BaseModel):
    question: str = Field(min_length=4, max_length=1000)
    max_steps: int = Field(default=settings.max_steps, ge=1, le=20)


@app.get("/api/status")
def status() -> dict[str, Any]:
    memory = MemoryStore(settings.db_path)
    try:
        registry = ToolRegistry(memory)
        health = registry.execute("source_health", {})
        return {
            "status": "online",
            "version": "0.2.0",
            "providers": health.data or {},
            "recent_runs": memory.recent_episodes(5),
        }
    finally:
        memory.close()


@app.get("/api/benchmarks")
def benchmarks() -> dict[str, Any]:
    rows = run_challenges()
    return {
        "passed": sum(bool(row["passed"]) for row in rows),
        "total": len(rows),
        "challenges": rows,
    }


@app.post("/api/research")
def research(request: ResearchRequest) -> dict[str, Any]:
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Enter a research question.")
    memory = MemoryStore(settings.db_path)
    try:
        agent = ResearchAgent(ToolRegistry(memory), memory, request.max_steps)
        run = agent.research(question)
        report = synthesize(question, run["observations"], run["metrics"])
        memory.remember_episode(question, report.executive_summary)
        return {
            "plan": run["plan"].model_dump(mode="json"),
            "observations": [
                item.model_dump(mode="json") for item in run["observations"]
            ],
            "report": report.model_dump(mode="json"),
            "metrics": run["metrics"],
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Research run failed: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        memory.close()



@app.get("/api/market/search")
def market_search(q: str = "") -> dict[str, Any]:
    """Search Yahoo's symbol directory and return verifiable issuer/listing candidates."""
    query = " ".join(q.split())
    if len(query) < 2 or len(query) > 100:
        raise HTTPException(status_code=422, detail="Enter a company name or ticker (2–100 characters).")
    try:
        matches = MarketProvider().search_symbols(query)
        return {"query": query, "provider": "Yahoo Finance symbol search", "matches": matches}
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Stock symbol search unavailable: {exc}") from exc


@app.get("/api/market/{symbol}")
def market_chart(symbol: str, period: str = "1y") -> dict[str, Any]:
    """Return timestamped public daily prices for the interactive stock chart."""
    ticker = symbol.upper().strip()
    if not re.fullmatch(r"[A-Z0-9.=-]{1,15}", ticker):
        raise HTTPException(status_code=422, detail="Invalid stock ticker.")
    if period not in {"1mo", "3mo", "6mo", "1y", "2y", "5y"}:
        raise HTTPException(status_code=422, detail="Unsupported chart period.")
    try:
        payload = MarketProvider().price_history(ticker, period)
        results = payload.get("chart", {}).get("result") or []
        if not results:
            raise ProviderError("Market provider returned no price observations.")
        row = results[0]
        quote = row.get("indicators", {}).get("quote", [{}])[0]
        timestamps = row.get("timestamp", [])
        closes = quote.get("close", [])
        points = [
            {"timestamp": timestamps[index], "close": closes[index]}
            for index in range(min(len(timestamps), len(closes)))
            if closes[index] is not None
        ]
        if len(points) < 2:
            raise ProviderError("Not enough daily price observations to draw a chart.")

        live_quote = None
        if settings.finnhub_api_key:
            try:
                quote_data = MarketProvider().quote(ticker)
                if quote_data.get("c") is not None:
                    live_quote = {
                        "price": quote_data.get("c"),
                        "change": quote_data.get("d"),
                        "change_percent": quote_data.get("dp"),
                        "timestamp": quote_data.get("t"),
                        "provider": "Finnhub",
                    }
            except ProviderError:
                live_quote = None

        return {
            "symbol": row.get("meta", {}).get("symbol") or ticker,
            "company": row.get("meta", {}).get("longName") or row.get("meta", {}).get("shortName"),
            "exchange": row.get("meta", {}).get("fullExchangeName") or row.get("meta", {}).get("exchangeName"),
            "currency": row.get("meta", {}).get("currency") or "USD",
            "provider": row.get("meta", {}).get("dataProvider") or "Yahoo Finance",
            "source_url": f"https://finance.yahoo.com/quote/{row.get('meta', {}).get('symbol') or ticker}",
            "period": period,
            "points": points,
            "latest": points[-1],
            "previous": points[-2],
            "live_quote": live_quote,
        }
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/market/{symbol}/forecast")
def market_forecast(symbol: str, horizon: int = 20) -> dict[str, Any]:
    """Build a transparent, evidence-linked statistical outlook from market history and indexed news."""
    ticker = symbol.upper().strip()
    if not re.fullmatch(r"[A-Z0-9.=-]{1,15}", ticker):
        raise HTTPException(status_code=422, detail="Invalid stock ticker.")
    if horizon not in {5, 20, 60}:
        raise HTTPException(status_code=422, detail="Forecast horizon must be 5, 20, or 60 trading days.")
    try:
        payload = MarketProvider().price_history(ticker, "1y")
        rows = payload.get("chart", {}).get("result") or []
        if not rows:
            raise ProviderError("No historical price series is available for forecasting.")
        row = rows[0]
        quote_row = row.get("indicators", {}).get("quote", [{}])[0]
        closes = [
            float(value) for value in quote_row.get("close", [])
            if value is not None and math.isfinite(float(value)) and float(value) > 0
        ]
        if len(closes) < 21:
            raise ProviderError(f"Forecast needs at least 21 valid daily closes; received {len(closes)}.")
        meta = row.get("meta", {})
        resolved_symbol = meta.get("symbol") or ticker
        company = meta.get("longName") or meta.get("shortName") or resolved_symbol
        provider = meta.get("dataProvider") or "Yahoo Finance"
        price_source = f"https://finance.yahoo.com/quote/{resolved_symbol}"
        log_returns = [math.log(closes[index] / closes[index - 1]) for index in range(1, len(closes))]
        recent20, recent60, long_window = log_returns[-20:], log_returns[-60:], log_returns[-252:]
        mean20 = sum(recent20) / len(recent20)
        mean60 = sum(recent60) / len(recent60)
        mean_long = sum(long_window) / len(long_window)
        blended_drift = 0.50 * mean20 + 0.30 * mean60 + 0.20 * mean_long
        daily_drift = blended_drift * 0.50
        vol_mean = sum(recent60) / len(recent60)
        daily_volatility = math.sqrt(
            sum((value - vol_mean) ** 2 for value in recent60) / max(1, len(recent60) - 1)
        )
        news_data: dict[str, Any] = {"articles": [], "provider": "Unavailable", "providers": []}
        news_error = None
        try:
            news_data = NewsProvider().search(f'"{company}" stock', 20)
        except ProviderError as exc:
            news_error = str(exc)
        articles = news_data.get("articles", [])
        positive_terms = {"growth", "beat", "beats", "upgrade", "profit", "surge", "record", "approval", "contract", "buyback", "strong", "expands"}
        negative_terms = {"loss", "miss", "misses", "downgrade", "lawsuit", "fraud", "probe", "decline", "cuts", "debt", "recall", "weak", "warning", "layoff"}
        positive = negative = 0
        for article in articles:
            words = set(re.findall(r"[a-z]+", (article.get("title") or "").lower()))
            positive += len(words & positive_terms)
            negative += len(words & negative_terms)
        sentiment_score = (positive - negative) / max(1, positive + negative)
        news_adjustment = max(-0.0005, min(0.0005, sentiment_score * 0.0005))
        adjusted_drift = daily_drift + news_adjustment
        last_price = closes[-1]
        expected = last_price * math.exp(adjusted_drift * horizon)
        interval = 1.28155 * daily_volatility * math.sqrt(horizon)
        lower = last_price * math.exp(adjusted_drift * horizon - interval)
        upper = last_price * math.exp(adjusted_drift * horizon + interval)
        momentum20 = closes[-1] / closes[-21] - 1
        momentum60 = closes[-1] / closes[-min(61, len(closes))] - 1
        expected_return = expected / last_price - 1
        outlook = "Positive bias" if expected_return > 0.01 else "Negative bias" if expected_return < -0.01 else "Neutral / mixed"
        coverage = min(1.0, len(closes) / 252)
        confidence_score = round(0.35 + 0.40 * coverage + (0.10 if len(articles) >= 5 else 0.04 if articles else 0.0), 2)
        source_list = [{
            "title": article.get("title") or "Untitled article",
            "publisher": (article.get("source") or {}).get("name") or "News index",
            "published_at": article.get("publishedAt"),
            "url": article.get("url"),
        } for article in articles[:12] if article.get("url")]
        return {
            "symbol": resolved_symbol, "company": company,
            "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
            "currency": meta.get("currency") or "USD", "provider": provider,
            "generated_at": datetime.now(UTC).isoformat(), "horizon_trading_days": horizon,
            "latest_close": last_price, "expected_price": expected, "expected_return": expected_return,
            "scenarios": {"bear": lower, "base": expected, "bull": upper},
            "range_level": "80% model interval (approximate, not a guarantee)",
            "daily_volatility": daily_volatility, "annualized_volatility": daily_volatility * math.sqrt(252),
            "momentum_20d": momentum20, "momentum_60d": momentum60, "outlook": outlook,
            "confidence_score": confidence_score,
            "confidence_note": "Data-coverage score, not the probability that the forecast will be correct.",
            "news": {
                "article_count": len(articles), "providers": news_data.get("providers", []),
                "sentiment_score": sentiment_score, "positive_signal_terms": positive,
                "negative_signal_terms": negative, "sources": source_list,
                "coverage_note": news_data.get("coverage_note") or "News search may be incomplete.",
                "error": news_error,
            },
            "method": "Explainable ensemble: weighted 20/60/252-session log-return drift, shrinkage toward zero, 60-session realized volatility and a capped headline-keyword adjustment.",
            "limitations": [
                "This is a statistical scenario model, not a guarantee or personalized investment advice.",
                "Headline keyword sentiment is a weak proxy; headlines can be misleading, duplicated or context-dependent.",
                "The interval assumes recent volatility is informative and does not model sudden gaps, corporate actions or all macro shocks.",
                "Past prices and indexed news cannot reliably predict future returns.",
            ],
            "sources": [{
                "name": f"{provider} daily price history", "url": price_source,
                "observations": len(closes),
                "last_observation_timestamp": (row.get("timestamp") or [None])[-1],
            }, *[{"name": item["publisher"], "url": item["url"], "published_at": item["published_at"]} for item in source_list]],
        }
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=f"Forecast unavailable: {exc}") from exc


@app.get("/api/history")
def history() -> dict[str, Any]:
    memory = MemoryStore(settings.db_path)
    try:
        return {"runs": memory.recent_episodes(20)}
    finally:
        memory.close()


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse({"ok": True})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")


def run() -> None:
    uvicorn.run("workbridge.web:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
