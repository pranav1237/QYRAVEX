from pathlib import Path

from workbridge.agent import Planner
from workbridge.benchmarks import run_challenges
from workbridge.memory import MemoryStore
from workbridge.models import Evidence, ToolResult
from workbridge.synthesis import detect_conflicts, synthesize


def test_planner_is_bounded_and_transparent():
    plan = Planner().build("Research MSFT financials and macro rates", max_steps=5)
    assert len(plan.steps) <= 5
    assert plan.steps[0].tool == "source_health"
    assert plan.assumptions
    named_company_plan = Planner().build("Research Microsoft financial performance")
    assert any(step.tool == "resolve_ticker" and step.args["ticker"] == "MSFT" for step in named_company_plan.steps)


def test_conflicts_are_not_silently_averaged():
    a = Evidence(id="1", statement="Revenue reported as 10", value=10, source="SEC", entity="X")
    b = Evidence(id="2", statement="Revenue reported as 12", value=12, source="Issuer", entity="X")
    conflicts = detect_conflicts([a, b])
    assert len(conflicts) == 1
    assert set(conflicts[0]["values"]) == {"10", "12"}


def test_memory_persists_and_searches(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory.sqlite")
    item = Evidence(
        id="abc",
        statement="Microsoft revenue increased",
        source="SEC",
        entity="Microsoft",
    )
    assert store.remember_evidence([item]) == 1
    assert store.search("Microsoft revenue")
    store.remember_evidence([item])
    assert store.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1
    store.close()


def test_partial_report_discloses_failure():
    report = synthesize(
        "test",
        [ToolResult(tool="news_search", success=False, error="offline")],
        {},
    )
    assert report.limitations
    assert report.evidence == []
    assert "did not return enough validated data" in report.executive_summary


def test_challenge_suite():
    rows = run_challenges()
    assert len(rows) == 8
    assert all(row["passed"] for row in rows)


def test_synthesis_builds_data_led_summary_and_source_metrics():
    evidence = Evidence(
        id="financial-1",
        statement="Example Corp revenue reported as 200",
        value=200,
        source="SEC EDGAR XBRL",
        entity="Example Corp",
        period="2025-12-31",
        unit="USD",
    )
    observations = [
        ToolResult(tool="resolve_ticker", success=True, data={"ticker": "EXM", "name": "Example Corp", "cik": "1"}),
        ToolResult(
            tool="financial_snapshot",
            success=True,
            data={
                "revenue": {"value": 200, "unit": "USD", "period_end": "2025-12-31"},
                "net_income": {"value": 30, "unit": "USD", "period_end": "2025-12-31"},
            },
            evidence=[evidence],
        ),
        ToolResult(
            tool="technical_summary",
            success=True,
            data={"period_return": 0.12, "annualized_volatility": 0.2, "max_drawdown": -0.08},
        ),
    ]
    report = synthesize("Review Example Corp", observations, {"tool_calls": 3})
    assert report.metrics["unique_sources"] == 1
    assert report.metrics["evidence_count"] == 1
    assert "Example Corp" in report.executive_summary
    assert "Net margin" in report.executive_summary
    assert "12.0%" in report.executive_summary



def test_news_synthesis_accepts_structured_provider_payload():
    observations = [
        ToolResult(
            tool="news_search",
            success=True,
            data={
                "provider": "Google News RSS",
                "articles": [
                    {
                        "title": "Example Corp announces quarterly results",
                        "source": {"name": "Example Publisher"},
                        "url": "https://example.com/results",
                    },
                    {
                        "title": "Analysts review Example Corp outlook",
                        "source": {"name": "Market Desk"},
                        "url": "https://example.com/outlook",
                    },
                ],
            },
        )
    ]
    report = synthesize("Research Example Corp", observations, {})
    assert any("Google News RSS" in finding for finding in report.findings)
    assert any("Example Corp announces quarterly results" in finding for finding in report.findings)
    assert not any("slice" in item for item in report.limitations)


def test_news_synthesis_still_accepts_legacy_article_list():
    observations = [
        ToolResult(
            tool="news_search",
            success=True,
            data=[
                {"title": "Example Corp legacy headline", "source": {"name": "Publisher"}}
            ],
        )
    ]
    report = synthesize("Research Example Corp", observations, {})
    assert any("Example Corp legacy headline" in finding for finding in report.findings)



def test_evidence_register_filters_records_to_specific_research_topic():
    from workbridge.synthesis import _matches_research_query

    assert _matches_research_query(
        "Microsoft Corp AI investment announced new data centre",
        "Microsoft AI investments",
    )
    assert not _matches_research_query(
        "Microsoft Corp revenue reported as 245 billion USD",
        "Microsoft AI investments",
    )
    assert _matches_research_query(
        "Apple iPhone sales increased in latest quarter",
        "AAPL iPhone sales",
    )
    assert not _matches_research_query(
        "Apple total assets reported as 300 billion USD",
        "AAPL iPhone sales",
    )


def test_news_findings_and_evidence_preserve_articles_returned_for_search_query():
    observations = [
        ToolResult(
            tool="news_search",
            success=True,
            data={
                "provider": "Google News RSS",
                "articles": [
                    {
                        "title": "Microsoft expands AI data centre investment",
                        "source": {"name": "Tech Publisher"},
                        "url": "https://example.com/microsoft-ai",
                    },
                    {
                        "title": "Microsoft reports quarterly revenue",
                        "source": {"name": "Finance Publisher"},
                        "url": "https://example.com/microsoft-revenue",
                    },
                ],
            },
            evidence=[
                Evidence(
                    id="ai-1",
                    statement="Microsoft expands AI data centre investment",
                    source="Tech Publisher",
                    source_url="https://example.com/microsoft-ai",
                    entity="Microsoft",
                ),
                Evidence(
                    id="revenue-1",
                    statement="Microsoft revenue reported as 245 billion USD",
                    source="Finance Publisher",
                    source_url="https://example.com/microsoft-revenue",
                    entity="Microsoft",
                ),
            ],
        )
    ]
    report = synthesize("Microsoft AI investment", observations, {})
    assert [item.id for item in report.evidence] == ["ai-1", "revenue-1"]
    assert any("Microsoft expands AI data centre investment" in item for item in report.findings)
    assert any("quarterly revenue" in item for item in report.findings)
