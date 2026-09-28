# Guardrails spec (`GR`)

Implementation: `viba_concierge/core/policy.py` (`PolicyEngine.check`, `guarded_call`).

`check(actor, tool, args)` returns exactly one verdict: `allow`,
`needs_confirmation`, or `deny`. Checks run in this order and the first failure
wins: unknown tool → unknown member → standing → entitlement → weekend tier →
confirmation. `guarded_call` executes the tool only on `allow` and raises
`GuardrailViolation` otherwise.

### GR-01 Side effects pause for member confirmation
**Rule.** A tool registered with `side_effect=True` MUST NOT execute until the
member has confirmed it (per tool, or by approving the itinerary).
**Acceptance.**
- Given no confirmation, when `book_tee_time` is called, then the verdict is
  `needs_confirmation` and the tee sheet is unchanged.
**Status.** enforced

### GR-02 Charge tools never auto-fire
**Rule.** Money-moving tools (`CHARGE_TOOLS` = `charge_folio`, `log_fuel`) MUST
require an explicit per-tool `confirm(tool)`. Itinerary-wide approval MUST NOT
unlock them.
**Acceptance.**
- Given no confirmation, when `charge_folio` is called, then no folio charge exists.
- Given `confirm_itinerary()` only, when `charge_folio` or `log_fuel` is called,
  then the verdict is `needs_confirmation` and no charge is posted.
- Given `confirm("charge_folio")`, when it is called, then the charge posts.
**Status.** enforced

### GR-03 Confirmation is scoped to one tool
**Rule.** `confirm(tool)` MUST unlock only that tool for the session.
**Acceptance.**
- Given `confirm("book_tee_time")`, when `charge_folio` is called, then it is blocked.
**Status.** enforced

### GR-04 Unknown tools are denied
**Rule.** A tool name absent from `TOOL_REGISTRY` MUST be denied.
**Acceptance.**
- When an unregistered tool is called, then the verdict is `deny`.
**Status.** enforced

### GR-05 Unknown members are denied
**Rule.** A `member_id` absent from the member store MUST be denied.
**Acceptance.**
- When any tool is called with `member_id="M-9999"`, then the verdict is `deny`.
**Status.** enforced

### GR-06 Standing gate (CC&R 9.1), waivable only by staff
**Rule.** A member whose standing is not `good` MUST be denied, even after
confirmation, with a reason citing CC&R 9.1. A staff override MAY waive this
gate; the waived decision MUST be audited with `override=true`.
**Acceptance.**
- Given a delinquent member and itinerary approval, when a booking is attempted,
  then the verdict is `deny` and the reason contains `9.1`.
- Given the same member and `staff_override=True`, then the verdict is `allow`
  and the audit entry has `override: true`.
**Status.** enforced

### GR-07 Entitlement gate is never overridable
**Rule.** A member lacking the entitlement for a tool's domain MUST be denied,
including under staff override. HOA tools require no entitlement.
**Acceptance.**
- Given `entitlements.golf = False`, when `book_tee_time` is called, then the
  verdict is `deny` and the reason names `golf`.
- Given the same member with `staff_override=True`, then it is still `deny`.
**Status.** enforced

### GR-08 Weekend access follows tier
**Rule.** A forward reservation on a Saturday or Sunday MUST be denied unless the
member's tier includes that day (`TIER_BENEFITS[tier].weekend_days`). Charges and
cancellations are exempt.
**Acceptance.**
- Silver on Saturday → `deny` ("Saturday access is not included").
- Gold on Saturday → `allow`; Gold on Sunday → `deny`.
- Platinum on either day → `allow`.
**Status.** enforced

### GR-09 PII never reaches the audit trail
**Rule.** Card numbers, SSNs, emails and residence identifiers MUST be redacted
before any argument is written to the audit log.
**Acceptance.**
- `redact()` replaces each with `[CARD]`, `[SSN]`, `[EMAIL]`, `[RESIDENCE]`.
**Status.** enforced

### GR-10 Every decision is audited
**Rule.** Each `check()` MUST append exactly one audit entry carrying actor,
tool, verdict, reason, redacted args and the override flag.
**Acceptance.**
- A blocked charge followed by an allowed read yields audit verdicts
  `["needs_confirmation", "allow"]`, in order.
**Status.** enforced
