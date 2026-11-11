"""Browser API and static dashboard for Zetheta WorkBridge."""
from __future__ import annotations

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
