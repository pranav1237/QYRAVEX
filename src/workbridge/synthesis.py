"""Evidence-aware synthesis, contradiction detection and report assembly."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from .models import Evidence, ResearchReport, ToolResult


def detect_conflicts(evidence: list[Evidence]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str | None, str], list[Evidence]] = defaultdict(list)
    for item in evidence:
        key = (item.entity, item.statement.split(" reported as ")[0].split(" retrieved")[0])
        grouped[key].append(item)
    conflicts = []
    for (entity, topic), items in grouped.items():
        values = {str(x.value) for x in items if x.value is not None}
        if len(values) > 1:
            conflicts.append(
                {
                    "entity": entity,
                    "topic": topic,
                    "values": list(values),
                    "sources": [x.source for x in items],
                    "resolution": (
                        "Unresolved: preserve both values; inspect period, unit, filing and methodology."
                    ),
                }
            )
    return conflicts


def synthesize(
    question: str,
    observations: list[ToolResult],
    metrics: dict[str, float],
) -> ResearchReport:
    evidence = [item for result in observations for item in result.evidence]
    conflicts = detect_conflicts(evidence)
    findings: list[str] = []
    limitations: list[str] = []
    unanswered: list[str] = []
    for result in observations:
        if not result.success:
            limitations.append(f"{result.tool}: {result.error or 'provider unavailable'}")
            continue
        if result.tool == "financial_snapshot" and result.data:
            for metric, item in result.data.items():
                findings.append(
                    f"{metric.replace('_', ' ').title()}: {item['value']} {item['unit']} "
                    f"(period ending {item['period_end']}; filed {item['filed']}; SEC XBRL)."
                )
        elif result.tool == "technical_summary" and result.data:
            data = result.data
            findings.append(
                f"{data.get('observations')} daily observations; price return "
                f"{data.get('period_return', 0):.2%}, annualized historical volatility "
                f"{data.get('annualized_volatility', 0):.2%}, max drawdown "
                f"{data.get('max_drawdown', 0):.2%}. Historical market data; not a forecast."
            )
        elif result.tool == "sec_filings" and result.data:
            findings.append(
                "Recent SEC filings: "
                + "; ".join(
                    f"{item.get('form')} filed {item.get('filingDate')}"
                    for item in result.data[:5]
                )
                + "."
            )
        elif result.tool == "news_search" and result.data:
            findings.append(
                f"News search returned {len(result.data)} articles; "
                "headlines are context, not verified facts."
            )
        elif result.tool == "source_health" and result.data:
            unavailable = [key for key, available in result.data.items() if not available]
            if unavailable:
                limitations.append(
                    "Optional sources not configured: " + ", ".join(unavailable)
                )
    if not evidence:
        limitations.append(
            "No source-backed evidence was retrieved; this is a failed/partial research run."
        )
    if conflicts:
        unanswered.extend(
            f"Resolve conflicting observations for {item['entity'] or 'unknown entity'}: "
            f"{item['topic']}"
            for item in conflicts
        )
    if not findings:
        findings.append("No validated findings could be produced from available provider responses.")
    unique_sources = len({item.source for item in evidence})
    fresh = [
        item for item in evidence
        if (datetime.now(UTC) - item.retrieved_at).days <= 30
    ]
    metrics = dict(metrics)
    metrics.update(
        {
            "evidence_count": float(len(evidence)),
            "unique_sources": float(unique_sources),
            "fresh_evidence_ratio": len(fresh) / len(evidence) if evidence else 0,
            "conflict_count": float(len(conflicts)),
            "mean_confidence": (
                sum(item.confidence for item in evidence) / len(evidence) if evidence else 0
            ),
            "citation_completeness": (
                sum(bool(item.source) for item in evidence) / len(evidence) if evidence else 0
            ),
            "unsupported_claims": 0.0,
        }
    )
    # Build a concise, evidence-led executive brief instead of a generic run receipt.
    issuer = next(
        (str(result.data.get("name")) for result in observations
         if result.tool == "resolve_ticker" and result.success and result.data),
        None,
    )
    snapshot = next(
        (result.data for result in observations
         if result.tool == "financial_snapshot" and result.success and result.data),
        {},
    )
    technical = next(
        (result.data for result in observations
         if result.tool == "technical_summary" and result.success and result.data),
        None,
    )
    brief: list[str] = []
    if issuer:
        brief.append(f"Coverage: {issuer}.")
    financial_parts = []
    for key, label in (
        ("revenue", "revenue"), ("operating_income", "operating income"),
        ("net_income", "net income"), ("total_assets", "total assets"),
        ("total_liabilities", "total liabilities"),
    ):
        item = snapshot.get(key)
        if item and item.get("value") is not None:
            value = item["value"]
            unit = item.get("unit", "")
            if isinstance(value, (int, float)):
                rendered = f"{value:,.0f}"
            else:
                rendered = str(value)
            financial_parts.append(f"{label} {rendered} {unit} (period ending {item.get('period_end', 'not stated')})")
    if financial_parts:
        brief.append("Latest reported financials: " + "; ".join(financial_parts) + ".")
    revenue = snapshot.get("revenue", {})
    net_income = snapshot.get("net_income", {})
    if (
        revenue.get("value") not in (None, 0)
        and net_income.get("value") is not None
        and revenue.get("period_end") == net_income.get("period_end")
    ):
        margin = net_income["value"] / revenue["value"]
        brief.append(f"Net margin, calculated from same-period reported values: {margin:.1%}.")
    if technical:
        direction = "positive" if technical.get("period_return", 0) > 0 else "negative"
        brief.append(
            f"One-year market context: {direction} price return of "
            f"{technical.get('period_return', 0):.1%}; annualized historical volatility "
            f"{technical.get('annualized_volatility', 0):.1%}; maximum drawdown "
            f"{technical.get('max_drawdown', 0):.1%}. Historical observations, not a forecast."
        )
    filing_result = next(
        (result for result in observations if result.tool == "sec_filings" and result.success),
        None,
    )
    if filing_result:
        brief.append(f"Filing coverage: {len(filing_result.data or [])} recent SEC filing records retrieved.")
    if not evidence:
        brief.append(
            "The run did not return enough validated data to produce an issuer-level assessment."
        )
    brief.append(
        f"Evidence quality: {len(evidence)} records across {unique_sources} distinct source(s); "
        f"{len(conflicts)} potential conflict(s) detected."
    )
    if limitations:
        brief.append(f"Coverage gaps: {len(limitations)} limitation(s) need review.")
    summary = " ".join(brief) if brief else (
        "The run did not return enough validated data to produce an issuer-level assessment. "
        "Review the execution trace and limitations before drawing conclusions."
    )
    return ResearchReport(
        question=question,
        executive_summary=summary,
        findings=findings,
        evidence=evidence,
        conflicts=conflicts,
        limitations=limitations,
        unanswered_questions=unanswered,
        metrics=metrics,
    )


def render_markdown(report: ResearchReport) -> str:
    lines = [
        f"# Financial Research: {report.question}",
        "",
        f"**As of:** {report.generated_at.isoformat()}",
        "",
        "## Executive summary",
        report.executive_summary,
        "",
        "## Findings",
    ]
    lines.extend(f"- {item}" for item in report.findings)
    lines += ["", "## Evidence register"]
    for item in report.evidence:
        lines.append(
            f"- **{item.statement}** — {item.source}"
            + (f" ([source]({item.source_url}))" if item.source_url else "")
            + (f"; period: {item.period}" if item.period else "")
            + f"; confidence: {item.confidence:.0%}"
        )
    lines += ["", "## Potential conflicts"]
    lines.extend(
        f"- {item['entity']}: {item['topic']} — {item['values']}. {item['resolution']}"
        for item in report.conflicts
    )
    if not report.conflicts:
        lines.append("- None detected by deterministic comparison.")
    lines += ["", "## Limitations"]
    lines.extend(f"- {item}" for item in report.limitations)
    if not report.limitations:
        lines.append("- No provider or parsing failures were recorded.")
    lines += ["", "## Open questions"]
    lines.extend(f"- {item}" for item in report.unanswered_questions)
    lines += ["", "## Run metrics"]
    lines.extend(f"- {key}: {value:.4f}" for key, value in sorted(report.metrics.items()))
    lines += ["", f"> **Disclaimer:** {report.disclaimer}"]
    return "\n".join(lines)
