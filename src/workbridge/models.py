"""Shared domain models. All evidence is provenance-bearing."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceKind(StrEnum):
    FACT = "fact"
    CALCULATION = "calculation"
    INTERPRETATION = "interpretation"
    UNKNOWN = "unknown"


class Evidence(BaseModel):
    id: str
    statement: str
    value: Any = None
    unit: str | None = None
    period: str | None = None
    source: str
    source_url: str | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    kind: EvidenceKind = EvidenceKind.FACT
    confidence: float = Field(default=0.8, ge=0, le=1)
    entity: str | None = None
    tags: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    tool: str
    success: bool
    data: Any = None
    evidence: list[Evidence] = Field(default_factory=list)
    error: str | None = None
    latency_ms: float = 0
    cached: bool = False
    warnings: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    id: int
    objective: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    required: bool = False


class ResearchPlan(BaseModel):
    question: str
    steps: list[PlanStep]
    assumptions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    question: str
    executive_summary: str
    findings: list[str]
    evidence: list[Evidence]
    conflicts: list[dict[str, Any]]
    limitations: list[str]
    unanswered_questions: list[str]
    metrics: dict[str, float]
    generated_at: datetime = Field(default_factory=utc_now)
    disclaimer: str = "Research support only; not investment advice."
