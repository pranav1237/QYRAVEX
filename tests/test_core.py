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


def test_challenge_suite():
    rows = run_challenges()
    assert len(rows) == 8
    assert all(row["passed"] for row in rows)
