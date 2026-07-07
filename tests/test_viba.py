"""Outcome-based tests: guardrails, memory, RAG, tools, and orchestration.

Principles: assert on final outcomes and state mutations, not internals;
verify security boundaries (never auto-charge, standing, entitlements,
registered-guest rules) as hard guarantees.
"""
from __future__ import annotations

import pytest

from viba_concierge.core.orchestrator import ConciergeOrchestrator
from viba_concierge.core.policy import (
    GuardrailViolation, PolicyEngine, Verdict, guarded_call, redact,
)
from viba_concierge.mcp_servers import connectors as c
from viba_concierge.mcp_servers.seed_data import STORE, SATURDAY, reset_store
from viba_concierge.core.governing_docs import TfidfRetriever, ask_governing_docs

ELEANOR = "M-1014"
REQUEST = ("Plan Saturday for me and three guests - morning golf, lunch at the "
           "Grill, afternoon tennis, sunset on the boat. Can my guests use the "
           "pool? Also, I'd like to repaint my front door navy - am I allowed?")


@pytest.fixture(autouse=True)
def _fresh_store():
    reset_store()
    yield
    reset_store()


# ------------------------------ guardrails --------------------------------

class TestGuardrails:
    def test_side_effect_blocked_without_confirmation(self):
        policy = PolicyEngine()
        with pytest.raises(GuardrailViolation) as err:
            guarded_call(policy, "test", "book_tee_time",
                         member_id=ELEANOR, day=SATURDAY, time="07:40", players=4)
        assert err.value.decision.verdict is Verdict.NEEDS_CONFIRMATION
        # outcome: state untouched
        assert STORE["golf_teesheet"][SATURDAY]["07:40"]["booked_by"] is None

    def test_charge_never_fires_without_confirmation(self):
        policy = PolicyEngine()
        with pytest.raises(GuardrailViolation):
            guarded_call(policy, "test", "charge_folio",
                         member_id=ELEANOR, amount=45.0, memo="pool passes")
        assert STORE["dining"]["folio_charges"] == []

    def test_confirmation_unlocks_single_tool_only(self):
        policy = PolicyEngine()
        policy.confirm("book_tee_time")
        result = guarded_call(policy, "test", "book_tee_time",
                              member_id=ELEANOR, day=SATURDAY, time="07:40", players=4)
        assert result["status"] == "booked"
        with pytest.raises(GuardrailViolation):
            guarded_call(policy, "test", "charge_folio",
                         member_id=ELEANOR, amount=1.0, memo="x")

    def test_itinerary_confirmation_never_unlocks_charge(self):
        # Blanket "yes, book it" must NOT authorize a money-movement tool.
        policy = PolicyEngine()
        policy.confirm_itinerary()
        with pytest.raises(GuardrailViolation) as err:
            guarded_call(policy, "test", "charge_folio",
                         member_id=ELEANOR, amount=45.0, memo="pool passes")
        assert err.value.decision.verdict is Verdict.NEEDS_CONFIRMATION
        assert STORE["dining"]["folio_charges"] == []
        # ...but an explicit per-tool confirmation does.
        policy.confirm("charge_folio")
        result = guarded_call(policy, "test", "charge_folio",
                              member_id=ELEANOR, amount=45.0, memo="pool passes")
        assert result["status"] == "charged"

    def test_bad_standing_denied_even_after_confirmation(self):
        STORE["members"][ELEANOR]["standing"] = "delinquent"
        policy = PolicyEngine()
        policy.confirm_itinerary()
        with pytest.raises(GuardrailViolation) as err:
            guarded_call(policy, "test", "book_tee_time",
                         member_id=ELEANOR, day=SATURDAY, time="07:40", players=4)
        assert err.value.decision.verdict is Verdict.DENY
        assert "9.1" in err.value.decision.reason

    def test_missing_entitlement_denied(self):
        STORE["members"][ELEANOR]["entitlements"]["golf"] = False
        policy = PolicyEngine()
        with pytest.raises(GuardrailViolation) as err:
            guarded_call(policy, "test", "list_tee_times_x", member_id=ELEANOR)
        assert err.value.decision.verdict is Verdict.DENY  # unknown tool
        with pytest.raises(GuardrailViolation) as err2:
            guarded_call(policy, "test", "book_tee_time",
                         member_id=ELEANOR, day=SATURDAY, time="07:40", players=4)
        assert err2.value.decision.verdict is Verdict.DENY
        assert "golf" in err2.value.decision.reason

    def test_unknown_member_denied(self):
        policy = PolicyEngine()
        with pytest.raises(GuardrailViolation) as err:
            guarded_call(policy, "test", "get_dues_status", member_id="M-9999")
        assert err.value.decision.verdict is Verdict.DENY

    def test_pii_redaction(self):
        text = redact("card 4111 1111 1111 1111, Villa 14, a@b.com, ssn 123-45-6789")
        assert "4111" not in text and "[CARD]" in text
        assert "Villa 14" not in text and "[RESIDENCE]" in text
        assert "a@b.com" not in text and "[EMAIL]" in text
        assert "123-45-6789" not in text and "[SSN]" in text

    def test_audit_trail_records_every_decision(self):
        policy = PolicyEngine()
        try:
            guarded_call(policy, "t", "charge_folio", member_id=ELEANOR,
                         amount=1.0, memo="x")
        except GuardrailViolation:
            pass
        guarded_call(policy, "t", "get_dues_status", member_id=ELEANOR)
        verdicts = [e["verdict"] for e in policy.audit.entries]
        assert verdicts == ["needs_confirmation", "allow"]


# ------------------------------ connectors --------------------------------

class TestConnectors:
    def test_registered_guest_rule_enforced(self):
        with pytest.raises(ValueError, match="not registered"):
            c.issue_guest_passes(ELEANOR, ["Stranger X."])

    def test_guest_pass_allotment_decrements(self):
        before = STORE["members"][ELEANOR]["entitlements"]["guest_passes_remaining"]
        c.issue_guest_passes(ELEANOR, ["Priya S.", "Daniel K."])
        after = STORE["members"][ELEANOR]["entitlements"]["guest_passes_remaining"]
        assert after == before - 2

    def test_double_booking_rejected(self):
        c.book_tee_time(ELEANOR, SATURDAY, "07:40", 4)
        with pytest.raises(ValueError, match="not available"):
            c.book_tee_time("M-2201", SATURDAY, "07:40", 2)

    def test_dining_capacity_enforced(self):
        assert c.check_dining_availability("The Grill", SATURDAY, 4)
        with pytest.raises(ValueError):
            c.reserve_table(ELEANOR, "The Grill", SATURDAY, "13:00", 4)  # 0 covers

    def test_side_effect_registry_classification(self):
        assert c.is_side_effect("charge_folio")
        assert c.is_side_effect("book_tee_time")
        assert not c.is_side_effect("list_tee_times")
        assert not c.is_side_effect("check_guest_pass_eligibility")


# ------------------- connectors: architecture-verb coverage ----------------

class TestArchitectureVerbs:
    """Every MCP tool verb promised in the architecture diagram is backed by a
    real connector: golf cancel, tennis join, aquatics lanes/cabana, marina
    fuel, dining menu."""

    def test_cancel_tee_time_only_by_booking_member(self):
        c.book_tee_time(ELEANOR, SATURDAY, "07:40", 4)
        with pytest.raises(ValueError, match="only the booking member"):
            c.cancel_tee_time("M-2201", SATURDAY, "07:40")
        result = c.cancel_tee_time(ELEANOR, SATURDAY, "07:40")
        assert result["status"] == "cancelled"
        assert STORE["golf_teesheet"][SATURDAY]["07:40"]["booked_by"] is None

    def test_join_clinic_takes_a_spot(self):
        before = STORE["clinics"][SATURDAY][0]["spots_open"]
        result = c.join_clinic(ELEANOR, SATURDAY, "Cardio Tennis")
        assert result["spots_open"] == before - 1
        assert ELEANOR in STORE["clinics"][SATURDAY][0]["roster"]
        with pytest.raises(ValueError, match="already enrolled"):
            c.join_clinic(ELEANOR, SATURDAY, "Cardio Tennis")

    def test_reserve_lane_decrements_open_lanes(self):
        before = STORE["aquatics"][SATURDAY]["lap_lanes_open"]
        assert c.reserve_lane(ELEANOR)["lap_lanes_open"] == before - 1

    def test_reserve_cabana_rejects_taken(self):
        assert c.reserve_cabana(ELEANOR, "C1")["status"] == "reserved"
        # C3 is seeded as already held by another member.
        with pytest.raises(ValueError, match="already reserved"):
            c.reserve_cabana(ELEANOR, "C3")

    def test_log_fuel_posts_folio_charge(self):
        result = c.log_fuel(ELEANOR, 10)
        assert result["amount"] == round(10 * STORE["marina"]["fuel_price_per_gal"], 2)
        assert len(STORE["marina"]["fuel_charges"]) == 1

    def test_fuel_is_never_auto_charged(self):
        # log_fuel moves money, so blanket itinerary approval must NOT unlock it.
        policy = PolicyEngine()
        policy.confirm_itinerary()
        with pytest.raises(GuardrailViolation) as err:
            guarded_call(policy, "test", "log_fuel", member_id=ELEANOR, gallons=10)
        assert err.value.decision.verdict is Verdict.NEEDS_CONFIRMATION
        assert STORE["marina"]["fuel_charges"] == []

    def test_get_menu_returns_items(self):
        menu = c.get_menu("The Grill")
        assert any(row["item"] == "Wagyu Burger" for row in menu)

    def test_every_diagram_verb_has_a_connector(self):
        for name in ("list_tee_times", "book_tee_time", "cancel_tee_time",
                     "list_courts", "reserve_court", "join_clinic",
                     "reserve_lane", "reserve_cabana", "check_guest_pass_eligibility",
                     "list_launch_windows", "log_fuel", "schedule_launch",
                     "reserve_table", "charge_folio", "get_menu",
                     "get_dues_status", "draft_arc_request"):
            assert name in c.TOOL_REGISTRY, f"missing connector: {name}"


# --------------------------------- tiers ----------------------------------

class TestTiers:
    """Membership tier is the single source of truth for facility access and
    guest-pass limits, and the entitlement gate enforces it."""

    def test_silver_lacks_tennis_and_marina(self):
        ent = STORE["members"]["M-3310"]["entitlements"]   # Priya, Silver
        assert ent["golf"] and ent["pool"] and ent["dining"]
        assert not ent["tennis"] and not ent["marina"]

    def test_gold_has_tennis_not_marina(self):
        ent = STORE["members"]["M-2760"]["entitlements"]   # Aisha, Gold
        assert ent["tennis"] and not ent["marina"]

    def test_platinum_has_all_facilities(self):
        ent = STORE["members"]["M-3021"]["entitlements"]   # Ravi, Platinum
        assert all(ent[f] for f in ("golf", "tennis", "pool", "marina", "dining"))

    def test_tier_drives_guest_pass_allotment(self):
        from viba_concierge.mcp_servers.seed_data import TIER_BENEFITS
        assert TIER_BENEFITS["Silver"]["annual_passes"] == 2
        assert TIER_BENEFITS["Gold"]["annual_passes"] == 4
        assert TIER_BENEFITS["Platinum"]["annual_passes"] == 6
        # a member's balance is clamped to their tier allotment at load
        assert STORE["members"]["M-3310"]["entitlements"]["guest_passes_remaining"] <= 2

    def test_silver_denied_marina_booking(self):
        # Tier-derived entitlement is enforced by the policy engine.
        policy = PolicyEngine()
        policy.confirm_itinerary()
        with pytest.raises(GuardrailViolation) as err:
            guarded_call(policy, "test", "schedule_launch",
                         member_id="M-3310", day=SATURDAY, time="18:30", passengers=[])
        assert err.value.decision.verdict is Verdict.DENY
        assert "marina" in err.value.decision.reason

    def test_weekend_access_is_tiered(self):
        from viba_concierge.mcp_servers.seed_data import SUNDAY
        policy = PolicyEngine()
        policy.confirm_itinerary()
        # Silver: no weekend access -> Saturday denied with the correct reason.
        sat_silver = policy.check("test", "book_tee_time",
                                  {"member_id": "M-3310", "day": SATURDAY, "time": "07:40", "players": 2})
        assert sat_silver.verdict is Verdict.DENY
        assert "Saturday access is not included" in sat_silver.reason
        # Gold: Saturday allowed, Sunday denied.
        sat_gold = policy.check("test", "book_tee_time",
                                {"member_id": "M-1188", "day": SATURDAY, "time": "07:40", "players": 4})
        assert sat_gold.verdict is Verdict.ALLOW
        sun_gold = policy.check("test", "book_tee_time",
                                {"member_id": "M-1188", "day": SUNDAY, "time": "07:40", "players": 4})
        assert sun_gold.verdict is Verdict.DENY
        assert "Sunday access is not included" in sun_gold.reason
        # Platinum: both weekend days allowed.
        for day in (SATURDAY, SUNDAY):
            dec = policy.check("test", "book_tee_time",
                               {"member_id": "M-1014", "day": day, "time": "07:40", "players": 4})
            assert dec.verdict is Verdict.ALLOW


# --------------------------------- rag ------------------------------------

class TestRag:
    def test_paint_question_hits_arc_rule(self):
        result = ask_governing_docs("can I repaint my front door navy")
        ids = [citation["doc_id"] for citation in result["citations"]]
        assert "ccr-4.2" in ids

    def test_paint_in_full_request_grounds_in_arc_not_golf(self):
        # Regression: the HOA agent must scope its RAG query to the exterior-
        # modification clause. Querying with the whole multi-intent request let
        # golf/pool wording dominate TF-IDF and mis-cite the Golf Guest Policy
        # (club-3.4) for the paint question, wrongly reporting "not pre-approved".
        result = ConciergeOrchestrator(ELEANOR).propose(REQUEST)
        hoa = [item for item in result.itinerary if item.domain == "hoa"]
        assert hoa, "expected an HOA (ARC) proposal"
        assert "ccr-4.2" in hoa[0].proposal
        assert "club-3.4" not in hoa[0].proposal
        # Classic Navy IS on the pre-approved palette per ccr-4.2 -> expedited.
        assert any("pre-approved palette" in note and "not on" not in note
                   for note in result.notes)

    def test_guest_pool_question_hits_guest_privileges(self):
        result = ask_governing_docs("can my guests use the pool guest pass")
        ids = [citation["doc_id"] for citation in result["citations"]]
        assert "club-7.1" in ids

    def test_scores_ranked_descending(self):
        cites = TfidfRetriever().search("guest pass pool", k=3)
        scores = [citation.score for citation in cites]
        assert scores == sorted(scores, reverse=True)


# ----------------------------- orchestration -------------------------------

class TestOrchestration:
    def test_full_flow_decomposes_all_six_intents(self):
        orchestrator = ConciergeOrchestrator(ELEANOR)
        result = orchestrator.propose(REQUEST)
        domains = {item.domain for item in result.itinerary}
        assert domains == {"golf", "dining", "tennis", "marina", "pool", "hoa"}

    def test_propose_commits_nothing(self):
        orchestrator = ConciergeOrchestrator(ELEANOR)
        orchestrator.propose(REQUEST)
        assert STORE["golf_teesheet"][SATURDAY]["07:40"]["booked_by"] is None
        assert STORE["dining"]["folio_charges"] == []
        assert STORE["hoa"]["arc_requests"] == []
        assert STORE["members"][ELEANOR]["entitlements"]["guest_passes_remaining"] == 6

    def test_confirm_commits_everything(self):
        orchestrator = ConciergeOrchestrator(ELEANOR)
        result = orchestrator.commit(orchestrator.propose(REQUEST), approved=True)
        assert all(item.status == "committed" for item in result.itinerary)
        assert STORE["golf_teesheet"][SATURDAY]["07:40"]["booked_by"] == ELEANOR
        assert STORE["hoa"]["arc_requests"][0]["status"].startswith("DRAFT")
        assert STORE["members"][ELEANOR]["entitlements"]["guest_passes_remaining"] == 3

    def test_decline_leaves_zero_side_effects(self):
        orchestrator = ConciergeOrchestrator(ELEANOR)
        result = orchestrator.commit(orchestrator.propose(REQUEST), approved=False)
        assert all(item.status == "declined" for item in result.itinerary)
        assert STORE["golf_teesheet"][SATURDAY]["07:40"]["booked_by"] is None
        assert STORE["hoa"]["arc_requests"] == []

    def test_gate_recorded_in_audit_before_confirmation(self):
        orchestrator = ConciergeOrchestrator(ELEANOR)
        result = orchestrator.propose(REQUEST)
        assert any("NEEDS_CONFIRMATION" in line for line in result.audit)

    def test_delinquent_member_gets_blocked_findings(self):
        STORE["members"][ELEANOR]["standing"] = "delinquent"
        orchestrator = ConciergeOrchestrator(ELEANOR)
        result = orchestrator.propose(REQUEST)
        # Only HOA services remain; all booking domains are gated out.
        assert all(item.domain == "hoa" for item in result.itinerary)
        assert any("CC&R 9.1" in note for note in result.notes)
        # and even the HOA draft cannot commit for a delinquent member
        committed = orchestrator.commit(result, approved=True)
        assert committed.committed == []

    def test_memory_history_appended_after_commit(self):
        orchestrator = ConciergeOrchestrator(ELEANOR)
        orchestrator.commit(orchestrator.propose(REQUEST), approved=True)
        history = STORE["members"][ELEANOR]["history"]
        assert {entry["type"] for entry in history} >= {"book_tee_time", "reserve_table"}
