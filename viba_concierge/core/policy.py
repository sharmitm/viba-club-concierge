"""Policy & guardrail layer.

Every delegation and tool action passes through PolicyEngine.check() before it
is allowed to execute:

  1. Entitlement check   - member standing and domain entitlements
  2. Confirmation gate   - side-effect tools require explicit member approval
  3. Never-auto-charge   - charge tools are hard-blocked without confirmation,
                           regardless of any agent reasoning
  4. PII redaction       - sensitive fields are masked before audit logging
  5. Audit logging       - immutable in-session trail of every decision
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from .logging import get_logger, log_event
from ..mcp_servers.connectors import TOOL_REGISTRY, is_side_effect
from ..mcp_servers.seed_data import STORE, TIER_BENEFITS

log = get_logger("viba.guardrails")

# Tools that move money. These are NEVER unlocked by blanket itinerary
# approval (confirm_itinerary): each requires its own explicit confirm(tool)
# so a charge can never ride in on a session-wide "yes, book it".
# issue_guest_passes is deliberately NOT here: its connector only decrements
# the member's pass allotment and never posts to the folio.
CHARGE_TOOLS = {"charge_folio", "log_fuel"}

# Map tool domain -> entitlement key on the member profile.
DOMAIN_ENTITLEMENT = {
    "golf": "golf", "tennis": "tennis", "pool": "pool",
    "marina": "marina", "dining": "dining", "hoa": None,  # HOA always allowed
}

_PII_PATTERNS = [
    (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), "[CARD]"),
    (re.compile(r"\bcard_last4['\":= ]+\d{4}"), "card_last4=[REDACTED]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
    (re.compile(r"\bVilla \d+\b"), "[RESIDENCE]"),
]


def redact(value: Any) -> str:
    """Redact PII from any value before it enters the audit trail."""
    text = str(value)
    for pattern, repl in _PII_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class Verdict(str, Enum):
    ALLOW = "allow"
    NEEDS_CONFIRMATION = "needs_confirmation"
    DENY = "deny"


@dataclass
class PolicyDecision:
    verdict: Verdict
    tool: str
    reason: str
    args_redacted: str = ""
    override: bool = False   # a standing gate waived by staff override


@dataclass
class AuditLog:
    entries: list[dict] = field(default_factory=list)

    def record(self, decision: PolicyDecision, actor: str) -> None:
        entry = {
            "ts": round(time.time(), 3),
            "actor": actor,
            "tool": decision.tool,
            "verdict": decision.verdict.value,
            "reason": decision.reason,
            "tool_args": decision.args_redacted,
            "override": decision.override,
        }
        self.entries.append(entry)
        log_event(log, "audit", **entry)

    def summary(self) -> list[str]:
        return [f"{e['verdict'].upper():>18}  {e['tool']}  ({e['reason']})"
                for e in self.entries]


class PolicyEngine:
    """Stateful per-session policy engine with an explicit confirmation set."""

    def __init__(self) -> None:
        self.audit = AuditLog()
        self._confirmed: set[str] = set()   # tool names the member approved
        self._session_confirmed_all = False
        self.staff_override = False          # staff waiver of the standing gate

    # ------------------------------------------------------------------
    def confirm(self, tool_name: str) -> None:
        """Member explicitly approved this side-effect tool for this session."""
        self._confirmed.add(tool_name)
        log_event(log, "member.confirmed", tool=tool_name)

    def confirm_itinerary(self) -> None:
        """Member approved the full proposed itinerary (all pending actions)."""
        self._session_confirmed_all = True
        log_event(log, "member.confirmed_itinerary")

    # ------------------------------------------------------------------
    def check(self, actor: str, tool_name: str, args: dict[str, Any]) -> PolicyDecision:
        args_red = redact(args)

        meta = TOOL_REGISTRY.get(tool_name)
        if meta is None:
            decision = PolicyDecision(Verdict.DENY, tool_name, "unknown tool", args_red)
            self.audit.record(decision, actor)
            return decision

        # 1. Entitlement check
        override_note = ""
        member_id = args.get("member_id")
        if member_id:
            member = STORE["members"].get(member_id)
            if member is None:
                decision = PolicyDecision(Verdict.DENY, tool_name, "unknown member", args_red)
                self.audit.record(decision, actor)
                return decision
            if member["standing"] != "good":
                # Standing is a temporary suspension -> staff may waive it (audited).
                if self.staff_override:
                    override_note = (f"standing '{member['standing']}' waived by "
                                     f"staff override (CC&R 9.1)")
                else:
                    decision = PolicyDecision(
                        Verdict.DENY, tool_name,
                        f"member standing is '{member['standing']}' (CC&R 9.1)", args_red)
                    self.audit.record(decision, actor)
                    return decision
            # Entitlement is NOT overridable: the member simply lacks this privilege.
            ent_key = DOMAIN_ENTITLEMENT.get(meta["domain"])
            if ent_key and not member["entitlements"].get(ent_key, False):
                decision = PolicyDecision(
                    Verdict.DENY, tool_name,
                    f"member lacks '{ent_key}' entitlement", args_red)
                self.audit.record(decision, actor)
                return decision

            # Weekend access is tiered: a member may only reserve on weekend days
            # their tier includes (applies to forward reservations, not cancels/charges).
            day = args.get("day")
            if (day and is_side_effect(tool_name)
                    and tool_name not in CHARGE_TOOLS and tool_name != "cancel_tee_time"):
                try:
                    booking = date.fromisoformat(str(day))
                except ValueError:
                    booking = None
                if booking and booking.weekday() >= 5:      # Sat=5, Sun=6
                    day_name = "Saturday" if booking.weekday() == 5 else "Sunday"
                    allowed = [d.lower() for d in
                               TIER_BENEFITS.get(member["tier"], {}).get("weekend_days", ())]
                    if day_name.lower() not in allowed:
                        grantors = [t for t, b in TIER_BENEFITS.items()
                                    if day_name.lower() in [d.lower() for d in b.get("weekend_days", ())]]
                        who = " and ".join(grantors) if grantors else "no"
                        decision = PolicyDecision(
                            Verdict.DENY, tool_name,
                            f"{day_name} access is not included in your {member['tier']} "
                            f"membership ({who} members only)", args_red)
                        self.audit.record(decision, actor)
                        return decision

        # 2 + 3. Confirmation gate / never-auto-charge
        if is_side_effect(tool_name):
            if tool_name in CHARGE_TOOLS:
                # Money-movement: only an explicit per-tool confirm counts.
                # Session-wide itinerary approval intentionally does NOT unlock it.
                confirmed = tool_name in self._confirmed
            else:
                confirmed = (tool_name in self._confirmed) or self._session_confirmed_all
            if not confirmed:
                reason = ("charge tool requires explicit confirmation (never auto-charge)"
                          if tool_name in CHARGE_TOOLS
                          else "side-effect tool paused for member confirmation")
                if override_note:
                    reason += f"; {override_note}"
                decision = PolicyDecision(Verdict.NEEDS_CONFIRMATION, tool_name, reason,
                                          args_red, override=bool(override_note))
                self.audit.record(decision, actor)
                return decision

        decision = PolicyDecision(
            Verdict.ALLOW, tool_name, override_note or "policy checks passed",
            args_red, override=bool(override_note))
        self.audit.record(decision, actor)
        return decision


class GuardrailViolation(Exception):
    def __init__(self, decision: PolicyDecision):
        self.decision = decision
        super().__init__(f"{decision.verdict.value}: {decision.tool} - {decision.reason}")


def guarded_call(policy: PolicyEngine, actor: str, tool_name: str, **args: Any) -> Any:
    """Execute a registered tool through the policy engine.

    Returns the tool result on ALLOW; raises GuardrailViolation on
    NEEDS_CONFIRMATION or DENY so the orchestrator can pause or refuse.
    """
    decision = policy.check(actor, tool_name, args)
    if decision.verdict is not Verdict.ALLOW:
        raise GuardrailViolation(decision)
    fn = TOOL_REGISTRY[tool_name]["fn"]
    try:
        return fn(**args)
    except Exception:
        log.error("tool.execution_error", extra={"tool": tool_name, "actor": actor},
                  exc_info=True)
        raise
