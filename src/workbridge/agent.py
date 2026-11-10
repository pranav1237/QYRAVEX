"""Bounded plan-and-execute agent with ReAct-style observations and fallbacks."""
from __future__ import annotations
import re
import time
from typing import Any
from .memory import MemoryStore
from .models import PlanStep, ResearchPlan, ToolResult
from .observability import Metrics
from .tools import ToolRegistry

class Planner:
    """Deterministic planner: transparent and reliable without requiring an LLM key."""
    def build(self, question: str, max_steps: int = 12) -> ResearchPlan:
        tickers = list(dict.fromkeys(re.findall(r"\b[A-Z]{1,5}\b", question)))
        tickers = [t for t in tickers if t not in {"THE", "AND", "FOR", "WITH", "FROM", "WHAT", "HOW", "SEC", "USD"}]
        steps: list[PlanStep] = []
        def add(objective: str, tool: str, args: dict[str, Any], rationale: str, required: bool = False) -> None:
            if len(steps) < max_steps:
                steps.append(PlanStep(id=len(steps)+1, objective=objective, tool=tool, args=args,
                                      rationale=rationale, required=required))
        add("Inspect provider availability", "source_health", {}, "Identify configured data sources.")
        add("Retrieve relevant prior evidence", "memory_search", {"query": question},
            "Reuse durable, provenance-bearing research when relevant.")
        for ticker in tickers[:3]:
            add(f"Resolve {ticker} to a legal entity and SEC CIK", "resolve_ticker",
                {"ticker": ticker}, "Map symbol to authoritative SEC registrant.")
            add(f"Retrieve reported financial statement facts for {ticker}", "financial_snapshot",
                {"cik": "__RESOLVED__"}, "Use SEC XBRL facts rather than inferred fundamentals.", True)
            add(f"Retrieve recent filings for {ticker}", "sec_filings",
                {"cik": "__RESOLVED__"}, "Identify current 10-K/10-Q and filing dates.")
            add(f"Retrieve market price history for {ticker}", "technical_summary",
                {"symbol": ticker, "period": "1y"}, "Provide dated market context, not intrinsic value.")
        if any(word in question.lower() for word in ("inflation", "rates", "macro", "economy", "gdp")):
            add("Retrieve macroeconomic context", "macro_series", {"series_id": "CPIAUCSL", "limit": 18},
                "Use public FRED observations; series choice is a proxy.")
        add("Search recent news context", "news_search", {"query": question, "page_size": 8},
            "Optional provider; disclose when unavailable.")
        return ResearchPlan(question=question, steps=steps,
            assumptions=["Ticker extraction is heuristic; validate the intended issuer.",
                         "Optional provider keys may be absent; core SEC and market tools remain usable."],
            success_criteria=["Use primary sources where available.", "Retain source and retrieval provenance.",
                              "Disclose missing data, conflicts, and provider outages."])

class ResearchAgent:
    def __init__(self, registry: ToolRegistry, memory: MemoryStore, max_steps: int = 12) -> None:
        self.registry, self.memory = registry, memory
        self.planner, self.max_steps = Planner(), max_steps
        self.metrics = Metrics()

    def research(self, question: str) -> dict[str, Any]:
        start = time.perf_counter()
        with self.metrics.measure("planning_latency_seconds"):
            plan = self.planner.build(question, self.max_steps)
        self.metrics.set("plan_steps", len(plan.steps))
        observations: list[ToolResult] = []
        resolved: dict[str, str] = {}
        for step in plan.steps:
            args = dict(step.args)
            if "__RESOLVED__" in args.values():
                match = re.search(r"\b[A-Z]{1,5}\b", step.objective)
                symbol = match.group(0) if match else ""
                if symbol not in resolved:
                    self.metrics.inc("skipped_steps")
                    observations.append(ToolResult(tool=step.tool, success=False,
                        error=f"Skipped: no resolved CIK for {symbol}"))
                    continue
                args = {k: resolved[symbol] if v == "__RESOLVED__" else v for k, v in args.items()}
            self.metrics.inc("tool_calls")
            self.metrics.event("tool_started", tool=step.tool, step=step.id)
            result = self.registry.execute(step.tool, args)
            if not result.success:
                self.metrics.inc("tool_failures")
                self.metrics.inc("fallback_count")
                self.metrics.event("tool_failed", tool=step.tool, error=result.error)
            else:
                self.metrics.inc("tool_successes")
                self.metrics.inc("completed_steps")
                self.metrics.inc("evidence_count", len(result.evidence))
                self.metrics.inc("cache_hits" if result.cached else "cache_misses")
                if step.tool == "resolve_ticker" and result.data:
                    resolved[result.data["ticker"]] = result.data["cik"]
            observations.append(result)
            if result.success and result.evidence:
                self.memory.remember_evidence(result.evidence)
        self.metrics.set("report_latency_seconds", time.perf_counter() - start)
        self.metrics.inc("provider_degradations", sum(
            1 for x in observations if not x.success and x.tool in {"company_profile", "news_search", "macro_series"}))
        return {"plan": plan, "observations": observations, "metrics": self.metrics.snapshot()}
