"""Concierge Orchestrator (viba-concierge root).

Pipeline: parse intent -> decompose -> delegate to domain sub-agents ->
aggregate into one itinerary -> PAUSE at the confirmation gate -> on member
approval, commit each side-effect action through the guardrail layer.

The deterministic decomposer below keeps the pipeline runnable and testable
without an LLM key; `agents/adk_app.py` swaps it for a Gemini-powered
LlmAgent when GOOGLE_API_KEY is set. Everything downstream (guardrails,
memory, tools, audit) is identical in both modes.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from .policy import (
    DOMAIN_ENTITLEMENT, GuardrailViolation, PolicyEngine, Verdict, guarded_call,
)
from .member_profile import ItineraryItem, MemberMemory
from .logging import current_agent, current_trace_id, get_logger, span
from .domains import HANDLERS

log = get_logger("viba.orchestrator")

# intent keyword -> domain (deterministic decomposition for dry-run mode)
_INTENT_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"golf|tee\b", re.I), "golf", "morning golf, member + 3 guests"),
    (re.compile(r"lunch|grill|dining|menu|table", re.I), "dining", "lunch at The Grill, party of 4"),
    (re.compile(r"tennis|court|pickle|clinic|coach", re.I), "tennis", "afternoon tennis"),
    (re.compile(r"boat|sunset|marina|cruise|fuel|slip", re.I), "marina", "sunset cruise from the marina"),
    (re.compile(r"pool|swim|cabana|lane|lap", re.I), "pool", "guest pool access for 3 guests"),
    (re.compile(r"paint|repaint|door|colou?r|fence|shed|awning|\bsign\b|exterior|\bhoa\b|"
                r"\barc\b|allowed|permit|approv|modif|install|landscap|deck|patio|antenna|"
                r"satellite|solar|window|guideline|governing|architectural|cc&r|ccr",
                re.I), "hoa", "HOA / home governance question"),
]


@dataclass
class ConciergeResult:
    trace_id: str
    itinerary: list[ItineraryItem]
    notes: list[str]
    audit: list[str]
    committed: list[ItineraryItem] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


class ConciergeOrchestrator:
    def __init__(self, member_id: str):
        self.policy = PolicyEngine()
        self.memory = MemberMemory(member_id)

    # ---------------------------- phase 1-4 -----------------------------
    def propose(self, request: str) -> ConciergeResult:
        """Decompose, delegate, aggregate. Ends PAUSED at the confirmation gate."""
        trace_id = uuid.uuid4().hex[:12]
        current_trace_id.set(trace_id)
        current_agent.set("viba-concierge")
        self.memory.session.raw_request = request

        with span("orchestrator.propose"):
            # Session-level gate: a member not in good standing forfeits booking
            # privileges (CC&R 9.1); only HOA (dues/governance) remains available.
            standing = self.memory.profile["standing"]
            domains = self._decompose(request)
            if standing != "good":
                self.memory.session.notes.append(
                    f"member standing is '{standing}': booking privileges suspended "
                    f"per CC&R 9.1; only HOA services available")
                domains = [(d, i) for d, i in domains if d == "hoa"]
                log.warning("standing.gate", extra={"standing": standing})
            else:
                # Tier gate: drop domains this member's tier doesn't include, with a note.
                ent = self.memory.profile["entitlements"]
                tier = self.memory.profile["tier"]
                kept = []
                for d, intent in domains:
                    key = DOMAIN_ENTITLEMENT.get(d)
                    if key and not ent.get(key, False):
                        self.memory.session.notes.append(
                            f"{d}: not included in your {tier} membership")
                    else:
                        kept.append((d, intent))
                domains = kept

            for domain, intent in domains:
                handler = HANDLERS[domain](self.policy, self.memory)
                try:
                    for item in handler.handle(intent):
                        self.memory.session.add_item(item)
                except GuardrailViolation as violation:
                    # A READ was denied (e.g. standing/entitlement): surface it.
                    self.memory.session.notes.append(
                        f"{domain}: blocked - {violation.decision.reason}")
                except Exception:
                    log.error("delegation.failed", extra={"domain": domain}, exc_info=True)
                    self.memory.session.notes.append(f"{domain}: unavailable (see error logs)")

            # Policy-check each proposed side-effect NOW: this records the pause in
            # the audit trail, and drops anything hard-denied (entitlement, booking
            # window) so the member only sees what they can actually book.
            bookable = []
            for item in self.memory.session.itinerary:
                decision = self.policy.check("viba-concierge", item.tool, item.args)
                if decision.verdict is Verdict.DENY:
                    self.memory.session.notes.append(f"{item.domain}: {decision.reason}")
                else:
                    bookable.append(item)
            self.memory.session.itinerary[:] = bookable

        return ConciergeResult(
            trace_id=trace_id,
            itinerary=list(self.memory.session.itinerary),
            notes=list(self.memory.session.notes),
            audit=self.policy.audit.summary(),
        )

    def _decompose(self, request: str) -> list[tuple[str, str]]:
        found, seen = [], set()
        for pattern, domain, canonical in _INTENT_RULES:
            if domain not in seen and pattern.search(request):
                seen.add(domain)
                found.append((domain, canonical))
        log.info("intent.decomposed", extra={"domains": [d for d, _ in found]})
        return found

    # ----------------------------- phase 5 ------------------------------
    def commit(self, result: ConciergeResult, approved: bool) -> ConciergeResult:
        """Member decision at the confirmation gate.

        approved=True unlocks side-effect tools for THIS session only; every
        commit still passes through the policy engine and audit log.
        """
        current_agent.set("viba-concierge")
        if not approved:
            for item in result.itinerary:
                item.status = "declined"
            log.info("itinerary.declined_by_member")
            result.audit = self.policy.audit.summary()
            return result

        self.policy.confirm_itinerary()
        with span("orchestrator.commit"):
            for item in result.itinerary:
                try:
                    item.result = guarded_call(
                        self.policy, "viba-concierge", item.tool, **item.args)
                    item.status = "committed"
                    result.committed.append(item)
                    self.memory.append_history(
                        {"type": item.tool, "domain": item.domain, "result": item.result})
                except GuardrailViolation as violation:
                    item.status = "failed"
                    result.blocked.append(str(violation))
                except Exception as err:
                    item.status = "failed"
                    result.blocked.append(f"{item.tool}: {err}")
                    log.error("commit.failed", extra={"tool": item.tool}, exc_info=True)
        result.audit = self.policy.audit.summary()
        return result
