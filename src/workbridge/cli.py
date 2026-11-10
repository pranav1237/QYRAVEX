"""Command line entry point."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .agent import ResearchAgent
from .config import settings
from .memory import MemoryStore
from .synthesis import render_markdown, synthesize
from .tools import ToolRegistry

app = typer.Typer(help="Zetheta WorkBridge financial research agent")
console = Console()


@app.command()
def research(
    question: str,
    format: Annotated[str, typer.Option(help="markdown or json")] = "markdown",
    max_steps: Annotated[int, typer.Option(min=1, max=40)] = settings.max_steps,
) -> None:
    """Research a company, sector, or macro-financial question."""
    memory = MemoryStore(settings.db_path)
    try:
        run = ResearchAgent(ToolRegistry(memory), memory, max_steps).research(question)
        report = synthesize(question, run["observations"], run["metrics"])
        memory.remember_episode(question, report.executive_summary)
        if format == "json":
            console.print_json(json.dumps(report.model_dump(mode="json")))
        else:
            console.print(render_markdown(report))
    finally:
        memory.close()


@app.command()
def benchmark(
    all: bool = typer.Option(False, "--all", help="Run all eight challenges"),
) -> None:
    """Run offline deterministic challenge suite."""
    from .benchmarks import run_challenges

    results = run_challenges()
    for row in results:
        console.print(
            f"[{'green' if row['passed'] else 'red'}]{row['id']} {row['title']}: "
            f"{'PASS' if row['passed'] else 'FAIL'}[/]"
        )
    console.print(f"{sum(x['passed'] for x in results)}/{len(results)} challenges passed")


@app.command()
def metrics(
    db: Path = typer.Option(settings.db_path, help="SQLite database path"),
) -> None:
    """Show durable memory row counts."""
    store = MemoryStore(db)
    try:
        console.print(
            {
                "durable_evidence_items": store.db.execute(
                    "SELECT COUNT(*) FROM facts"
                ).fetchone()[0],
                "research_episodes": store.db.execute(
                    "SELECT COUNT(*) FROM episodes"
                ).fetchone()[0],
            }
        )
    finally:
        store.close()


if __name__ == "__main__":
    app()
