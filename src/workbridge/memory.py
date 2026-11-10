"""Three-layer memory: run context, durable facts, and searchable episodes."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import Evidence


class MemoryStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS facts (
          id TEXT PRIMARY KEY, entity TEXT, statement TEXT, payload TEXT, source TEXT,
          retrieved_at TEXT, confidence REAL
        );
        CREATE TABLE IF NOT EXISTS episodes (
          id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, summary TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity);
        """)
        self.db.commit()
        self.run_context: dict[str, Any] = {}

    def remember_evidence(self, items: list[Evidence]) -> int:
        count = 0
        for item in items:
            self.db.execute(
                "INSERT OR REPLACE INTO facts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item.id, item.entity, item.statement, json.dumps(item.model_dump(mode="json")),
                 item.source, item.retrieved_at.isoformat(), item.confidence),
            )
            count += 1
        self.db.commit()
        return count

    def search(self, query: str, limit: int = 8) -> list[Evidence]:
        tokens = [t.lower() for t in query.split() if len(t) > 2]
        rows = self.db.execute("SELECT payload FROM facts ORDER BY retrieved_at DESC LIMIT 500").fetchall()
        ranked: list[tuple[int, Evidence]] = []
        for row in rows:
            payload = json.loads(row["payload"])
            haystack = (payload.get("statement", "") + " " + str(payload.get("entity", ""))).lower()
            score = sum(token in haystack for token in tokens)
            if score:
                ranked.append((score, Evidence.model_validate(payload)))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[:limit]]

    def remember_episode(self, question: str, summary: str) -> None:
        self.db.execute("INSERT INTO episodes(question, summary) VALUES (?, ?)", (question, summary))
        self.db.commit()

    def recent_episodes(self, limit: int = 5) -> list[dict[str, str]]:
        rows = self.db.execute(
            "SELECT question, summary, created_at FROM episodes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.db.close()
