# QYRAVEX — Autonomous Financial Intelligence\n\n**Research Beyond the Obvious.**

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
workbridge research "Compare Microsoft and Alphabet's latest reported revenue growth, margins, and balance-sheet risks"
```

The core research workflow uses public live sources without paid API keys: SEC EDGAR for issuer facts and filings, Yahoo Finance with Stooq daily-price fallback, FRED's public graph CSV for macro observations, and GDELT DOC 2.0 for recent news metadata. Finnhub company news and live quote data plus NewsAPI article search are optional enrichments, not prerequisites. Configure `FINNHUB_API_KEY` and `NEWSAPI_API_KEY` in your local `.env` or deployment environment secrets to activate them; never commit real keys. Each run records source URLs and retrieval timestamps; provider outages are disclosed rather than replaced with invented data.

## What it does

- Plans a multi-step research task and selects tools from a typed registry.
- Executes bounded ReAct steps with timeouts, retries, backoff, and graceful degradation.
- Retrieves SEC company facts and filings, daily market prices (Yahoo Finance with Stooq fallback), public FRED macro series, GDELT-indexed news, and cached local research.
- Stores short-term run context, persistent SQLite knowledge, and semantic-style retrieval indexes (TF-IDF fallback; optional embeddings are an extension point).
- Tracks provenance, freshness, coverage, contradictions, confidence, and unresolved questions.
- Synthesizes a report that separates sourced facts, calculations, interpretations, and unknowns.
- Exposes 25+ operational/research quality metrics and eight progressive benchmark challenges.

## Browser dashboard

A browser dashboard is included. Install the updated dependencies and launch it with:

```bash
pip install -e ".[dev]"
workbridge-web
```

Open `http://localhost:8000` (or open forwarded port 8000 in GitHub Codespaces). The dashboard provides a research form, execution trace, evidence register, provider status, saved run history, and the offline benchmark suite. The API is also documented at `/docs`.

In Codespaces, use the **Ports** panel to open port `8000` in your browser. No separate Node.js frontend build is required.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/TOOLS.md](docs/TOOLS.md), [docs/METRICS.md](docs/METRICS.md), and [docs/CHALLENGES.md](docs/CHALLENGES.md).

## Configuration

See [.env.example](.env.example). No API key is required for the core SEC/market/FRED/GDELT sources. Create keys at [Finnhub](https://finnhub.io/register) and [NewsAPI](https://newsapi.org/register), then set `FINNHUB_API_KEY` and `NEWSAPI_API_KEY` in `.env` or your hosting provider's environment variables. Restart the web service after setting them. Finnhub adds company news and a live quote to the stock chart; NewsAPI adds another news feed. SEC requests identify the application with a descriptive User-Agent; replace the example `SEC_USER_AGENT` with your project name and a valid contact email before using SEC endpoints.

## CLI

```bash
workbridge research "Research NVDA: business, latest financials, valuation context, risks" --format markdown
workbridge research "..." --format json --max-steps 16
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
