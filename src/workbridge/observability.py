"""Run metrics and structured event collection."""
from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager


class Metrics:
    NAMES = (
        "tool_calls", "tool_successes", "tool_failures", "tool_retries", "tool_timeouts",
        "cache_hits", "cache_misses", "plan_steps", "completed_steps", "skipped_steps",
        "evidence_count", "unique_sources", "fresh_evidence_ratio", "source_coverage",
        "conflict_count", "resolved_conflicts", "unresolved_conflicts", "mean_confidence",
        "low_confidence_claims", "unsupported_claims", "report_latency_seconds",
        "planning_latency_seconds", "synthesis_latency_seconds", "tokens_estimated",
        "fallback_count", "provider_degradations", "memory_reads", "memory_writes",
        "retrieval_hits", "retrieval_misses", "citation_completeness", "entity_coverage",
    )

    def __init__(self) -> None:
        self.values: dict[str, float] = defaultdict(float)
        self.events: list[dict[str, object]] = []
        self.started = time.perf_counter()

    def inc(self, name: str, amount: float = 1) -> None:
        self.values[name] += amount

    def set(self, name: str, value: float) -> None:
        self.values[name] = value

    def event(self, name: str, **fields: object) -> None:
        self.events.append({"event": name, "at": time.time(), **fields})

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.set(name, time.perf_counter() - start)

    def snapshot(self) -> dict[str, float]:
        result = {name: float(self.values.get(name, 0)) for name in self.NAMES}
        result["elapsed_seconds"] = time.perf_counter() - self.started
        return result
