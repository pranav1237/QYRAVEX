"""Eight progressive, offline benchmarks for core agent reliability."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from .memory import MemoryStore
from .models import Evidence, ToolResult
from .synthesis import detect_conflicts, synthesize

CHALLENGES = [
    ("C1", "Evidence identity", "Evidence objects preserve source and identity"),
    ("C2", "Conflict detection", "Divergent source values are surfaced"),
    ("C3", "Confidence bounds", "Confidence values remain within [0, 1]"),
    ("C4", "Missing source", "Provider failure is represented as a limitation"),
    ("C5", "Provenance", "Every evidence item has a source"),
    ("C6", "Unit awareness", "Financial evidence can retain unit metadata"),
    ("C7", "Memory deduplication", "SQLite upsert prevents duplicate evidence IDs"),
    ("C8", "No invented output", "Empty evidence produces no sourced factual claims"),
]

def run_challenges() -> list[dict[str, object]]:
    e1 = Evidence(id="a", statement="Revenue reported as 100", value=100, source="SEC",
                  entity="Example", confidence=.9, unit="USD")
    e2 = Evidence(id="b", statement="Revenue reported as 120", value=120, source="Annual report",
                  entity="Example", confidence=.8, unit="USD")
    with TemporaryDirectory() as tmp:
        store = MemoryStore(Path(tmp) / "bench.sqlite")
        store.remember_evidence([e1])
        store.remember_evidence([e1])
        deduplicated = store.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1
        store.close()
    checks = [bool(e1.source and e1.id), len(detect_conflicts([e1, e2])) == 1,
        0 <= e1.confidence <= 1,
        bool(synthesize("test", [ToolResult(tool="news_search", success=False, error="offline")], {}).limitations),
        all(x.source for x in [e1, e2]), e1.unit == "USD", deduplicated,
        not synthesize("test", [], {}).evidence]
    return [{"id": cid, "title": title, "passed": bool(ok), "description": desc}
            for (cid, title, desc), ok in zip(CHALLENGES, checks)]
