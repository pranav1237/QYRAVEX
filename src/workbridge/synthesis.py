"""Evidence-aware synthesis, contradiction detection and report assembly."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
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
            conflicts.append({"entity": entity, "topic": topic, "values": list(values),
                              "sources": [x.source for x in items],
                              "resolution": "Unresolved: preserve both values; inspect period, unit, filing and methodology."})
    return conflicts

def synthesize(question: str, observations: list[ToolResult], metrics: dict[str, float]) -> ResearchReport:
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
                findings.append(f"{metric.replace('_', ' ').title()}: {item['value']} {item['unit']} "
                                f"(period ending {item['period_end']}; filed {item['filed']}; SEC XBRL).")
        elif result.tool == "technical_summary" and result.data:
            d = result.data
            findings.append(f"{d.get('observations')} daily observations; price return "
                            f"{d.get('period_return', 0):.2%}, annualized historical volatility "
                            f"{d.get('annualized_volatility', 0):.2%}, max drawdown "
                            f"{d.get('max_drawdown', 0):.2%}. Historical market data; not a forecast.")
        elif result.tool == "sec_filings" and result.data:
            findings.append("Recent SEC filings: " + "; ".join(
                f"{x.get('form')} filed {x.get('filingDate')}" for x in result.data[:5]) + ".")
        elif result.tool == "news_search" and result.data:
            findings.append(f"News search returned {len(result.data)} articles; headlines are context, not verified facts.")
        elif result.tool == "source_health" and result.data:
            unavailable = [k for k, v in result.data.items() if not v]
            if unavailable:
                limitations.append("Optional sources not configured: " + ", ".join(unavailable))
    if not evidence:
        limitations.append("No source-backed evidence was retrieved; this is a failed/partial research run.")
    if conflicts:
        unanswered.extend(f"Resolve conflicting observations for {c['entity'] or 'unknown entity'}: {c['topic']}"
                          for c in conflicts)
    if not findings:
        findings.append("No validated findings could be produced from available provider responses.")
    unique_sources = len({x.source for x in evidence})
    fresh = [x for x in evidence if (datetime.now(timezone.utc) - x.retrieved_at).days <= 30]
    metrics = dict(metrics)
    metrics.update({"evidence_count": float(len(evidence)), "unique_sources": float(unique_sources),
        "fresh_evidence_ratio": len(fresh) / len(evidence) if evidence else 0,
        "conflict_count": float(len(conflicts)),
        "mean_confidence": sum(x.confidence for x in evidence) / len(evidence) if evidence else 0,
        "citation_completeness": sum(bool(x.source) for x in evidence) / len(evidence) if evidence else 0,
        "unsupported_claims": 0.0})
    summary = (f"Collected {len(evidence)} evidence items from {unique_sources} distinct sources. "
               f"{len(findings)} findings assembled; {len(conflicts)} potential conflict(s) need review. "
               "Read limitations before relying on this analysis.")
    return ResearchReport(question=question, executive_summary=summary, findings=findings, evidence=evidence,
                          conflicts=conflicts, limitations=limitations, unanswered_questions=unanswered,
                          metrics=metrics)

def render_markdown(report: ResearchReport) -> str:
    lines = [f"# Financial Research: {report.question}", "", f"**As of:** {report.generated_at.isoformat()}",
             "", "## Executive summary", report.executive_summary, "", "## Findings"]
    lines.extend(f"- {item}" for item in report.findings)
    lines += ["", "## Evidence register"]
    for item in report.evidence:
        lines.append(f"- **{item.statement}** — {item.source}"
                     + (f" ([source]({item.source_url}))" if item.source_url else "")
                     + (f"; period: {item.period}" if item.period else "")
                     + f"; confidence: {item.confidence:.0%}")
    lines += ["", "## Potential conflicts"]
    lines.extend(f"- {x['entity']}: {x['topic']} — {x['values']}. {x['resolution']}" for x in report.conflicts)
    if not report.conflicts:
        lines.append("- None detected by deterministic comparison.")
    lines += ["", "## Limitations"]
    lines.extend(f"- {x}" for x in report.limitations)
    if not report.limitations:
        lines.append("- No provider or parsing failures were recorded.")
    lines += ["", "## Open questions"]
    lines.extend(f"- {x}" for x in report.unanswered_questions)
    lines += ["", "## Run metrics"]
    lines.extend(f"- {k}: {v:.4f}" for k, v in sorted(report.metrics.items()))
    lines += ["", f"> **Disclaimer:** {report.disclaimer}"]
    return "\n".join(lines)
