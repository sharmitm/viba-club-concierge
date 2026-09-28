"""Tests for spec requirements that test_viba.py did not yet prove.

Written spec-first: each test implements the acceptance criteria of the
requirement named in its marker (see specs/).
"""
from __future__ import annotations

import io
import json
import logging
from types import SimpleNamespace

import pytest

from viba_concierge.core import domains
from viba_concierge.core.logging import JsonFormatter, span
from viba_concierge.core.orchestrator import ConciergeOrchestrator
from viba_concierge.core.policy import PolicyEngine, Verdict
from viba_concierge.mcp_servers.seed_data import STORE, SATURDAY, reset_store

from .test_viba import ELEANOR, REQUEST


@pytest.fixture(autouse=True)
def _fresh_store():
    reset_store()
    yield
    reset_store()


@pytest.fixture
def captured_logs():
    """Capture root-logger output as parsed JSON records."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield lambda: [json.loads(line) for line in buf.getvalue().splitlines()]
    finally:
        root.removeHandler(handler)


def _book(member_id: str = ELEANOR) -> dict:
    return {"member_id": member_id, "day": SATURDAY, "time": "07:40", "players": 4}


# ------------------------------ guardrails --------------------------------

@pytest.mark.spec("GR-06", "GR-10")
def test_staff_override_waives_standing_and_is_audited():
    STORE["members"][ELEANOR]["standing"] = "delinquent"
    policy = PolicyEngine()
    policy.confirm_itinerary()
    policy.staff_override = True
    decision = policy.check("staff", "book_tee_time", _book())
    assert decision.verdict is Verdict.ALLOW
    assert "staff override" in decision.reason
    assert policy.audit.entries[-1]["override"] is True


@pytest.mark.spec("GR-07")
def test_staff_override_never_waives_entitlement():
    STORE["members"][ELEANOR]["standing"] = "delinquent"
    STORE["members"][ELEANOR]["entitlements"]["golf"] = False
    policy = PolicyEngine()
    policy.confirm_itinerary()
    policy.staff_override = True
    decision = policy.check("staff", "book_tee_time", _book())
    assert decision.verdict is Verdict.DENY
    assert "golf" in decision.reason


# ----------------------------- orchestration -------------------------------

@pytest.mark.spec("OR-07")
def test_tier_excluded_domain_dropped_with_note():
    result = ConciergeOrchestrator("M-2760").propose(REQUEST)   # Aisha, Gold
    assert "marina" not in {item.domain for item in result.itinerary}
    assert "marina: not included in your Gold membership" in result.notes


@pytest.mark.spec("OR-08")
def test_failing_sub_agent_does_not_sink_request(monkeypatch):
    class BrokenGolf(domains.DomainHandler):
        name = domain = "golf"

        def _handle(self, intent):
            raise RuntimeError("tee sheet offline")

    monkeypatch.setitem(domains.HANDLERS, "golf", BrokenGolf)
    result = ConciergeOrchestrator(ELEANOR).propose(REQUEST)
    assert {item.domain for item in result.itinerary} == {
        "dining", "tennis", "marina", "pool", "hoa"}
    assert "golf: unavailable (see error logs)" in result.notes


# ----------------------------- observability -------------------------------

@pytest.mark.spec("OB-01")
def test_one_request_is_one_trace(captured_logs):
    orchestrator = ConciergeOrchestrator(ELEANOR)
    result = orchestrator.propose(REQUEST)
    records = captured_logs()
    assert records, "expected structured log output"
    assert {r["trace_id"] for r in records} == {result.trace_id}
    agents = {r["agent"] for r in records}
    assert "viba-concierge" in agents and len(agents) > 1


@pytest.mark.spec("OB-02")
def test_span_times_success(captured_logs):
    with span("unit.ok"):
        pass
    events = {r["msg"]: r for r in captured_logs() if r.get("span") == "unit.ok"}
    assert set(events) == {"span.start", "span.end"}
    assert isinstance(events["span.end"]["duration_ms"], float)


@pytest.mark.spec("OB-02")
def test_span_logs_and_reraises_errors(captured_logs):
    with pytest.raises(RuntimeError, match="boom"):
        with span("unit.fail"):
            raise RuntimeError("boom")
    errors = [r for r in captured_logs() if r["msg"] == "span.error"]
    assert len(errors) == 1
    assert "boom" in errors[0]["error"] and "duration_ms" in errors[0]


# ------------------------------- live mode ---------------------------------

@pytest.mark.spec("LV-01")
def test_adk_callback_gates_registered_tools():
    pytest.importorskip("google.adk")
    from viba_concierge.agents import adk_app

    tool = SimpleNamespace(name="book_tee_time")
    blocked = adk_app._guardrail_before_tool(tool, _book(), tool_context=None)
    assert blocked["blocked"] is True
    assert blocked["verdict"] == Verdict.NEEDS_CONFIRMATION.value
    framework = SimpleNamespace(name="transfer_to_agent")
    assert adk_app._guardrail_before_tool(framework, {}, tool_context=None) is None
