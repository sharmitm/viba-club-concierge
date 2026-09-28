# Orchestration spec (`OR`)

Implementation: `viba_concierge/core/orchestrator.py` (`ConciergeOrchestrator`),
`viba_concierge/core/domains.py` (sub-agent handlers),
`viba_concierge/core/member_profile.py` (shared memory).

Reference scenario ("Eleanor's request", member `M-1014`, Platinum):

> Plan Saturday for me and three guests - morning golf, lunch at the Grill,
> afternoon tennis, sunset on the boat. Can my guests use the pool? Also, I'd
> like to repaint my front door navy - am I allowed?

### OR-01 One request decomposes into every domain it names
**Rule.** `propose()` MUST produce itinerary items for each domain the request
mentions.
**Acceptance.**
- The reference request yields items for exactly
  `{golf, dining, tennis, marina, pool, hoa}`.
**Status.** enforced

### OR-02 Proposing has zero side effects
**Rule.** `propose()` MUST only read and propose. No booking, charge, pass or
draft may be written.
**Acceptance.**
- After `propose()`, the tee time is unbooked, there are no folio charges or ARC
  requests, and the guest-pass balance is unchanged (6).
**Status.** enforced

### OR-03 The pause is audited before the member answers
**Rule.** `propose()` MUST policy-check every proposed side effect so the audit
trail shows `NEEDS_CONFIRMATION` before any approval.
**Acceptance.**
- The proposal's audit summary contains a `NEEDS_CONFIRMATION` line.
**Status.** enforced

### OR-04 Approval commits every item through the guardrails
**Rule.** `commit(approved=True)` MUST execute each item via `guarded_call`, mark
it `committed`, and never bypass the policy engine.
**Acceptance.**
- Every item is `committed`; the tee time is held by the member; the ARC request
  is a draft; three guest passes are consumed (6 → 3).
**Status.** enforced

### OR-05 Declining leaves the world untouched
**Rule.** `commit(approved=False)` MUST mark every item `declined` and write nothing.
**Acceptance.**
- After decline, the tee time is unbooked and there are no ARC requests.
**Status.** enforced

### OR-06 Standing gate at the session level
**Rule.** For a member not in good standing, `propose()` MUST drop every booking
domain, keep only HOA, and add a note citing CC&R 9.1. Nothing may commit.
**Acceptance.**
- A delinquent Eleanor gets only HOA items, a `CC&R 9.1` note, and an empty
  `committed` list after approval.
**Status.** enforced

### OR-07 Tier-excluded domains are dropped with an explanation
**Rule.** A domain the member's tier does not include MUST be removed from the
itinerary and explained in a note, not silently ignored.
**Acceptance.**
- A Gold member making the reference request gets no marina item and a note
  "marina: not included in your Gold membership".
**Status.** enforced

### OR-08 A failing sub-agent does not sink the request
**Rule.** If one domain handler raises an unexpected error, the other domains
MUST still be proposed and the failed domain MUST be reported in the notes.
**Acceptance.**
- With the golf handler forced to raise, the itinerary still has the other five
  domains and the notes contain "golf: unavailable".
**Status.** enforced

### OR-09 Confirmed actions become member history
**Rule.** Each committed item MUST be appended to the member's history in shared
memory.
**Acceptance.**
- After approval, history includes `book_tee_time` and `reserve_table` entries.
**Status.** enforced
