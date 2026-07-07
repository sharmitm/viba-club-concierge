# Viba Club Member Concierge

### One request. Six clubs. No forms.

*Google × Kaggle — AI Agents Intensive: Vibe Coding Capstone (Concierge track)*

---

## The problem a form can't solve

A luxury residential club runs on six disconnected systems of record — a golf tee sheet, a tennis court grid, an aquatics registry, a marina ledger, a dining POS, and an HOA governance portal. Each has its own login, its own rules, and its own idea of who you are.

A member doesn't think in systems. Eleanor types one sentence:

> *"Plan Saturday for me and three guests — morning golf, lunch at the Grill, afternoon tennis, sunset on the boat. Can my guests use the pool? Also, I'd like to repaint my front door navy — am I allowed?"*

That single request spans all six systems, mixes **actions** (book, reserve, charge) with **questions** (eligibility, governance), and touches money and rules that must not be gotten wrong. No booking form could ever span it. **The product is the orchestration** — decompose the request, reason over availability, entitlements, and governing documents, chain the actions, and confirm with the member before anything is booked or charged.

That is what Viba Concierge does — from a CLI, from a browser, and under a live Gemini agent, all driving the same guarded core.

---

## What it does, end to end

One natural-language request fans out to six domain sub-agents over a shared member profile. Each sub-agent reads the relevant system of record, consults governing documents where policy is implicated, and **proposes** an itinerary item — it never commits. The orchestrator aggregates the six proposals into one plan and **pauses at a hard confirmation gate**. Nothing is booked and nothing is charged until the member says yes. On approval, each action commits through the same guarded path; on decline, the store is provably untouched.

Here is a real run (`python scripts/demo.py`), unedited:

```
MEMBER REQUEST (Eleanor R.)
  "Plan Saturday for me and three guests — morning golf, lunch at the Grill,
   afternoon tennis, sunset on the boat. Can my guests use the pool? Also,
   I'd like to repaint my front door navy — am I allowed?"

TRACE f9f409d6c900 — PROPOSED ITINERARY (6 actions, none committed)
  1. [  golf] Golf 2026-07-11 at 07:40 for 4 (prefers morning tee times; guest fees per [club-3.4])
  2. [dining] Lunch at The Grill 12:00, party of 4 (window table, no shellfish for one guest)
  3. [tennis] Tennis on court-1 at 14:00
  4. [marina] Sunset launch at 18:30, 4 aboard (own vessel 'Second Wind', slip B-07)
  5. [  pool] Pool guest passes for Priya S., Daniel K., Maya L. (uses 3 of 6 remaining, [club-7.1])
  6. [   hoa] Draft ARC request — front door repaint (Navy), grounded in [ccr-4.2] (draft only)

FINDINGS
  - pool: guests ELIGIBLE (6 passes remaining) per [club-7.1]
  - hoa: Navy front door is on the pre-approved palette (expedited ~5 business days) per [ccr-4.2]; ARC approval still required

GATE ACTIVE: paused for member confirmation. Nothing booked, nothing charged.

MEMBER CONFIRMED — committing 6 actions
  OK  book_tee_time     OK  reserve_table     OK  reserve_court
  OK  schedule_launch   OK  issue_guest_passes  OK  draft_arc_request
```

The two **questions** were answered with citations (`[club-7.1]`, `[ccr-4.2]`), the **HOA request was drafted, never submitted**, and every side effect waited for one word.

**The same flow, in a browser.** `python3 scripts/webapp.py` serves a zero-dependency (stdlib `http.server` only, no API key) member surface at `localhost:8000` that drives the *same* `ConciergeOrchestrator`. What you see in the browser is the real propose → gate → confirm/decline → commit flow with the live guardrail audit trail rendered as a table. Beyond the anchor "Plan my Saturday" story, it exposes:

- **À-la-carte actions** — book a single tee time, join a clinic, reserve a cabana or lane, log fuel — each member-supplied action routed through the *same* PolicyEngine: reads execute immediately; side-effect tools return `needs_confirmation` and re-lock after every run so the gate shows every time; charge tools every time.
- **A member dashboard** — one read-only snapshot of every system of record (tee sheet, courts, clinics, cabanas, lanes, dining covers, folio, dues, ARC requests) and *this member's* holdings.
- **Login and a staff role** (see Responsible AI, below).
- **A live-mode toggle** that runs the request under a real Gemini agent instead of the deterministic core — same gate, same audit.

---

## Architecture

```
01  Member surface     CLI demo · stdlib web app · live-mode toggle (streaming NL)
02  Orchestration      viba-concierge root agent + shared member memory
03  Guardrails         PolicyEngine — every delegation and action passes through
04  Domain sub-agents  golf · dining · tennis · marina · pool · hoa
05  Tool layer         20 tools (13 side-effecting) · 6 FastMCP servers (stdio)
06  Systems of record  8 members, mocked · seeded · deterministic
```

Six architectural decisions carry the build:

**1. One tool registry, two transports.** Connector functions are plain Python, tagged with a `@tool(domain, side_effect=...)` decorator. ADK sub-agents wrap them as `FunctionTool`s; the same functions are exposed over MCP by six FastMCP servers, and the web app calls them directly. There is no code fork across CLI, web, MCP, and live deployment, and — crucially — the side-effect classification travels *with the function*, which is exactly what the guardrails key on. A test (`test_every_diagram_verb_has_a_connector`) asserts the architecture diagram and the code can't drift.

**2. Guardrails as a chokepoint, not a suggestion.** `PolicyEngine.check()` runs before every tool execution, in every mode. In dry-run and web mode, `guarded_call()` is the only path to a tool. In live ADK mode, the same engine is attached as a `before_tool_callback` on the root agent *and every sub-agent* — returning a dict short-circuits the tool, so no model output can route around it. Check order: unknown tool → unknown member → bad standing (CC&R 9.1) → missing entitlement → side effect without confirmation. The two money tools (`charge_folio`, `log_fuel`) carry an explicit **never-auto-charge** rule and can never ride in on a session-wide "yes."

**3. Propose then commit (two-phase itinerary).** Sub-agents only READ and PROPOSE. Each proposal carries the exact side-effect tool and args that *would* commit it. The orchestrator policy-checks every proposed action during the propose phase, so the audit trail visibly records the pause (`NEEDS_CONFIRMATION` rows) *before* the member answers. Approval unlocks the session; decline discards it with zero side effects. In live mode the member's click — not a model tool call — deterministically lifts the gate, mirroring the dry-run `commit()`.

**4. Shared member memory as the coordination surface.** `MemberMemory` fronts the member record (profile, preferences, registered guests, entitlements, standing, consent) plus session memory (raw request, decomposed intents, itinerary, cross-agent notes). Sub-agents read preferences to shape proposals — morning tee times, window table, slip B-07 — and write findings the orchestrator folds into one answer. The seed carries **eight members** across Platinum/Gold/Silver tiers and good/delinquent/suspended standing, so the policy paths are demonstrable, not hypothetical.

**5. RAG with mandatory citations.** Governing docs (CC&Rs, club and marina rules) are retrieved via a `Retriever` protocol; every policy claim attaches a `[doc-id]` cite. Production swaps embeddings behind the protocol without touching agents. "Can my guests use the pool?" and "am I allowed to paint my door navy?" are **grounded, not guessed**.

**6. Deterministic core, LLM shell.** The decompose → delegate → aggregate → confirm → commit pipeline runs with **no API key** (rule-based handlers), which makes it fully testable and gives live mode a regression baseline. `adk_app.py` swaps in Gemini `LlmAgent`s while keeping guardrails, memory, tools, RAG, and audit identical; `live.py` captures every ADK event as a structured trace row the UI renders. **The LLM improves the interface; it cannot weaken the invariants.**

---

## Course concepts — the rubric asks for ≥3; this covers four

| Key concept (rubric) | Where | In the code / video |
|---|---|---|
| **Agent / Multi-agent system (ADK)** | Code | `core/orchestrator.py`, `agents/adk_app.py`, `agents/live.py` — root `LlmAgent` + 6 sub-agents; one request fans out and reconciles into one itinerary, in CLI, web, and live modes |
| **MCP Server** | Code | `mcp_servers/serve.py` — 6 FastMCP servers over stdio, 20 tools; the *same* functions back the ADK agents (`connectors.py`) |
| **Security features** | Code + Video | `core/policy.py` — `NEEDS_CONFIRMATION` for every side effect before approval; charge tools can never auto-fire; standing/entitlement checks; PII redaction; role-gated, audited staff override. 39 outcome tests |
| **Deployability** | Video | `scripts/webapp.py` — stdlib-only web app, no API key, reproducible from the README; runs the identical guarded core |

*(Bonus beyond the required three: **RAG** over governing docs with mandatory `[doc-id]` citations (`core/governing_docs.py`), and **shared member memory** as the coordination surface (`core/member_profile.py`).)*

All of it is exercised by a **single run** of `scripts/demo.py`, and again through the browser.

---

## Responsible AI — enforced in state, not prompts

The safety story is the interesting engineering, so it is tested on outcomes, not mocks. **39 tests pass** covering:

- **Never auto-charge** — the two money tools (`charge_folio`, `log_fuel`) are hard-blocked without confirmation, independent of model behavior. `test_charge_never_fires_without_confirmation`, `test_fuel_is_never_auto_charged`, `test_itinerary_confirmation_never_unlocks_charge`.
- **Confirmation unlocks one tool, once** — approving the itinerary does not hand the agent a blank check. `test_confirmation_unlocks_single_tool_only`.
- **Standing & entitlements from governing docs** — a delinquent member is blocked *even after confirming*; a suspended account is locked out of the whole action panel. `test_bad_standing_denied_even_after_confirmation`, `test_delinquent_member_gets_blocked_findings`, `test_missing_entitlement_denied`.
- **Staff override is a governed exception, not a backdoor** — only the `staff` role can waive the standing gate; the waiver never applies to a charge, and every override is recorded in the audit with an `override: true` flag and a cited reason (`... waived by staff override (CC&R 9.1)`). Members cannot self-override.
- **Ownership & capacity at the connector, not just the prompt** — cancel only by the booking member, guest-pass allotment, double-booking, dining capacity, clinic spots, lane counts, taken cabanas. `test_cancel_tee_time_only_by_booking_member`, `test_guest_pass_allotment_decrements`, `test_double_booking_rejected`, `test_reserve_cabana_rejects_taken`, `test_reserve_lane_decrements_open_lanes`, `test_join_clinic_takes_a_spot`.
- **PII redaction** before anything enters the audit trail. `test_pii_redaction`.
- **Human agency preserved** — the ARC request is *drafted only*; submission stays with the member.
- **Full-flow guarantees** — `test_propose_commits_nothing`, `test_confirm_commits_everything`, `test_decline_leaves_zero_side_effects`, `test_gate_recorded_in_audit_before_confirmation`.

Every request is one **trace_id**, followable across the orchestrator, six sub-agents, guardrail verdicts, and tool calls via structured JSON logs with timing spans — and in live mode, across every Gemini event too. This observability caught two real bugs during the build (a `LogRecord` key collision and a decomposition gap) purely from the error logs — which is the point of building it first.

---

## Run it yourself

```bash
pip install -r requirements.txt

# CLI (no API key)
python scripts/demo.py            # propose → gate → confirm → commit
python scripts/demo.py --decline  # member declines: zero side effects
python scripts/demo.py --json     # machine-readable result

# Browser (no API key) — same orchestrator, live audit table
python3 scripts/webapp.py         # http://localhost:8000

python -m pytest tests/ -q        # 39 outcome-based tests

# Live mode (Gemini via ADK) — same guardrails
export GOOGLE_API_KEY=...
adk web viba_concierge/agents     # or flip the web app's live toggle
```

---

## Limitations & next steps

- **Systems of record are mocked and seeded** for a deterministic demo. The connector seam is real — each function has a clear input/output contract — so production swaps in live APIs behind the same `@tool` signatures without touching agents or guardrails.
- **RAG uses deterministic TF-IDF** so the demo is reproducible offline. The `Retriever` protocol swaps in embeddings for production with no agent changes.
- **Live-mode decomposition can drift** from the deterministic baseline; the rule-based pipeline is kept as the regression oracle, compared intent-set to intent-set per request.
- **The web app is a single-user local session** (a plain dict of server-side sessions) — deliberately, for the demo. Multi-tenant auth, per-member session isolation, and MCP transport swapped in per sub-agent in live mode are the productionization steps, along with an `agents-cli eval` set built from the 39 test scenarios.

---

*Repo map, design rationale, and the two-week rubric-mapped plan are in `README.md`, `DESIGN.md`, and `IMPLEMENTATION_PLAN.md`.*
