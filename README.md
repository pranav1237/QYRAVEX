# Zetheta WorkBridge — Autonomous Financial Research Agent

A source-grounded, auditable financial research agent built around a **Plan → Act → Observe → Reflect → Synthesize** loop. It combines deterministic financial-data tools, bounded ReAct execution, SQLite-backed memory, evidence-aware synthesis, and explicit reliability controls.

> **Research support only.** This software is not investment advice, does not execute trades, and must not be used as the sole basis for financial decisions. Market data and provider coverage vary. Every generated claim should retain its source and retrieval time.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
workbridge "Compare Microsoft and Alphabet's latest reported revenue growth, margins, and balance-sheet risks"
```

The core SEC tools work without API keys. Optional providers are enabled by environment variables; missing credentials are reported as unavailable capabilities rather than silently fabricated.

## What it does

- Plans a multi-step research task and selects tools from a typed registry.
- Executes bounded ReAct steps with timeouts, retries, backoff, and graceful degradation.
- Retrieves SEC company facts and filings, price history, macro series, company profiles, news, and cached local research.
- Stores short-term run context, persistent SQLite knowledge, and semantic-style retrieval indexes (TF-IDF fallback; optional embeddings are an extension point).
- Tracks provenance, freshness, coverage, contradictions, confidence, and unresolved questions.
- Synthesizes a report that separates sourced facts, calculations, interpretations, and unknowns.
- Exposes 25+ operational/research quality metrics and eight progressive benchmark challenges.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/TOOLS.md](docs/TOOLS.md), [docs/METRICS.md](docs/METRICS.md), and [docs/CHALLENGES.md](docs/CHALLENGES.md).

## Configuration

See [.env.example](.env.example). Provider keys are optional. SEC requests identify the application with a descriptive User-Agent; set `SEC_USER_AGENT` to a valid contact string before using SEC endpoints at scale.

## CLI

```bash
workbridge "Research NVDA: business, latest financials, valuation context, risks" --format markdown
workbridge "..." --format json --max-steps 16
workbridge benchmark --all
workbridge metrics --db ./data/workbridge.sqlite
```

## Safety and reliability

- No broker, order-placement, or account-authentication tools are registered.
- No investment recommendation is generated as a guaranteed outcome.
- Provider output is untrusted input; the agent treats retrieved text as evidence, never as instructions.
- Numerical claims include units, periods, and provenance when available.
- Conflicts are preserved and surfaced, not averaged away without justification.
- A report can be partial; missing sources and degraded provider status are explicit.
- Secrets are read from environment variables and are never written to memory or reports.

## Development

```bash
pip install -e ".[dev]"
ruff check .
mypy src
pytest -q
```

## License

Internal project deliverable. Add the license approved by the project owner before external distribution.
