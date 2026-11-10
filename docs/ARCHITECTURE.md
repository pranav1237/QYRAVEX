# Architecture and execution model

## Control loop

1. **Plan:** deterministic planner turns the question into bounded typed steps. The plan is inspectable and contains rationale, assumptions, and success criteria.
2. **Act:** registry dispatches only named, allowlisted tools with typed Python boundaries.
3. **Observe:** each tool returns success/failure, data, evidence, latency, cache state, and warnings.
4. **Reflect:** resolved SEC identifiers feed subsequent tasks; evidence is persisted; failed optional sources trigger a partial-result path.
5. **Synthesize:** evidence is grouped, conflicts are surfaced, limitations are retained, and a report is rendered with a source register.

The baseline uses a deterministic planner rather than pretending to have an LLM planner when no model credential is configured. This makes the shipped path reproducible and testable. An LLM planner can be added behind the Planner interface, with schema validation and the same bounded registry.

## Memory layers

- **Layer 1 — working memory:** per-run plan, resolved entities, observations, and scratch context in ResearchAgent.
- **Layer 2 — durable semantic facts:** SQLite facts table; stores serialized Evidence with source, retrieval time, period, entity, unit, and confidence.
- **Layer 3 — episodic memory:** SQLite episodes table; stores prior question and executive summary for run continuity.

Retrieval is a lightweight lexical relevance baseline. It intentionally does not claim embedding-level semantic search. Optional embedding retrieval can be added behind MemoryStore.search.

## Trust boundaries

Provider payloads are external untrusted data. They are parsed as data and never interpreted as instructions. Tool names are allowlisted. No arbitrary shell, browser, trading, brokerage, or account-management tools are registered. Credentials are read from environment variables and are not stored in SQLite.

## Failure strategy

HTTP requests use finite timeouts and bounded retries with exponential backoff. Tool boundaries convert exceptions into structured failures. Optional providers can be absent; the report remains partial and explains missing integrations. A missing CIK prevents issuer-specific financial calls instead of substituting another company.
