"""Browser API and static dashboard for Zetheta WorkBridge."""
from __future__ import annotations

import re
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
from .providers import MarketProvider, ProviderError
from .synthesis import synthesize
from .tools import ToolRegistry

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Zetheta WorkBridge",
    version="0.2.0",
    description="Evidence-aware financial research workspace",
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
        return {
            "symbol": ticker,
            "currency": row.get("meta", {}).get("currency") or "USD",
            "provider": row.get("meta", {}).get("dataProvider") or "Yahoo Finance",
            "period": period,
            "points": points,
            "latest": points[-1],
            "previous": points[-2],
            "live_quote": live_quote,
        }
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

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
