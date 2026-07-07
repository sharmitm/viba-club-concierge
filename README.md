# Viba Club Member Concierge

### One request. Six systems. No forms.

A multi-agent concierge for the **Google × Kaggle — AI Agents Intensive: Vibe Coding Capstone**, **Concierge Agents track**. A single natural-language member request fans out to six domain sub-agents (golf, dining, tennis, marina, pool, HOA) over shared member memory. Each proposes; none commit. A guardrail layer pauses for member confirmation before anything is booked or charged, answers policy questions with citations from the governing documents, and drafts — never submits — the HOA architectural request. The same guarded core runs from a CLI, from a zero-dependency web app, and under a live Gemini agent.

> **Concierge track fit:** the track asks for agents that *"keep personal information safe and secure."* That is this project's spine — a policy chokepoint every action passes through, PII redacted before it touches the audit log, money tools that can never auto-charge, and staff overrides that are role-gated and logged. Safety is the feature, and it is tested on outcomes.

---

## The problem

A luxury residential club runs on six disconnected systems of record — a golf tee sheet, a tennis court grid, an aquatics registry, a marina ledger, a dining POS, and an HOA governance portal. Each has its own login and its own rules. A member doesn't think in systems; she thinks in one sentence:

> *"Plan Saturday for me and three guests — morning golf, lunch at the Grill, afternoon tennis, sunset on the boat. Can my guests use the pool? Also, I'd like to repaint my front door navy — am I allowed?"*

That request spans all six systems, mixes **actions** (book, reserve, charge) with **questions** (eligibility, governance), and touches money and rules that must not be gotten wrong. **No booking form could span it — the product is the orchestration.**

## The solution

Decompose the request → delegate to six domain sub-agents over a shared member profile → each reads its system of record, consults governing docs where policy applies, and **proposes** an itinerary item → the orchestrator aggregates one plan and **pauses at a hard confirmation gate** → on approval each action commits through the same guarded path; on decline, the store is provably untouched.

## Course concepts demonstrated (≥3 required)

| Key concept | Where | In this repo |
|---|---|---|
| **Agent / Multi-agent system (ADK)** | Code | `core/orchestrator.py` + `agents/adk_app.py` (root `LlmAgent` + 6 sub-agents) + `agents/live.py` |
| **MCP Server** | Code | `mcp_servers/serve.py` — 6 FastMCP servers over stdio, 20 tools, same functions back the ADK agents |
| **Security features** | Code + Video | `core/policy.py` — confirmation gates, never-auto-charge, standing/entitlement checks, PII redaction, role-gated staff override, audit log; asserted by 39 outcome tests |
| **Deployability** | Video | `scripts/webapp.py` — stdlib-only web app, no API key, reproducible from this README |

*(Plus RAG over governing docs with mandatory citations, and shared member memory as the coordination surface.)*

---

## Architecture

```
01  Member surface     CLI demo · designed web dashboard (localhost:8000) · live-mode toggle
02  Orchestration      viba-concierge root agent + shared member memory
03  Guardrails         PolicyEngine — every delegation and action passes through
04  Domain sub-agents  golf · dining · tennis · marina · pool · hoa
05  Tool layer         20 tools (13 side-effecting) · 6 FastMCP servers (stdio)
06  Systems of record  8 members · mocked · seeded · deterministic
```

*(An architecture diagram is included in the Media Gallery / `docs`; `tests/test_viba.py::test_every_diagram_verb_has_a_connector` asserts the diagram and the code cannot drift.)*

**Five design decisions carry the build** (full rationale in `DESIGN.md`):

1. **One tool registry, two transports.** Connectors are plain Python tagged `@tool(domain, side_effect=...)`. ADK sub-agents wrap them as `FunctionTool`s; FastMCP exposes the same functions over MCP; the web app calls them directly. No fork across CLI / web / MCP / live, and the side-effect flag travels *with the function* — which is what the guardrails key on.
2. **Guardrails as a chokepoint, not a suggestion.** `PolicyEngine.check()` runs before every tool. In dry-run/web it is the only path to a tool; in live mode it is a `before_tool_callback` on the root agent *and every sub-agent*, so no model output can route around it.
3. **Propose then commit.** Sub-agents only READ and PROPOSE; the audit records a `NEEDS_CONFIRMATION` row for every side effect *before* the member answers. The member's decision — not a model tool call — lifts the gate.
4. **Shared member memory** carries profile, preferences, registered guests, entitlements, and standing; sub-agents read it to shape proposals and write findings the orchestrator folds into one answer.
5. **Deterministic core, LLM shell.** The whole pipeline runs with **no API key** (rule-based), which makes it fully testable and gives live mode a regression baseline. Gemini improves the interface; it cannot weaken the invariants.

---

## Setup & run

Requires Python ≥ 3.11.

```bash
pip install -r requirements.txt

# 1) CLI — the anchor story, no API key
python scripts/demo.py            # propose → gate → confirm → commit
python scripts/demo.py --decline  # member declines: zero side effects
python scripts/demo.py --json     # machine-readable result

# 2) Browser — designed member dashboard (scripts/ui.html), same orchestrator, no API key
python3 scripts/webapp.py         # open http://localhost:8000
#   chat bar + one-tap prompts · "Your day, perfectly planned" timeline · Today-at-a-glance
#   à-la-carte actions · staff override · live audit table · live-mode toggle
#   zero dependencies (stdlib http.server) — no framework, no build step

# 3) Tests — the security boundaries, asserted on state
python -m pytest tests/ -q        # 39 passing

# 4) MCP servers — each domain standalone over stdio
python -m viba_concierge.mcp_servers.serve golf   # tennis|dining|pool|marina|hoa

# 5) Live mode (Gemini via ADK) — optional, needs a key (see below)
export GOOGLE_API_KEY=...          # or put it in .env (gitignored)
adk web viba_concierge/agents      # root agent: viba_concierge
```

Structured JSON traces stream to stderr (`trace_id`, `agent`, spans with `duration_ms`): `python scripts/demo.py 2>trace.log`.

### 🔑 API keys — none are committed

The CLI, web app, and full test suite need **no key**. Live mode reads `GOOGLE_API_KEY` from your environment or a local `.env` (see `.env.example`). **`.env` is gitignored — never commit a real key.**

---

## Responsible AI (39 outcome-based tests)

- **Never auto-charge** — money tools (`charge_folio`, `log_fuel`) hard-blocked without confirmation, model-independent.
- **Confirmation unlocks one tool, once** — approval is not a blank check.
- **Standing & entitlements from governing docs** — a delinquent member is blocked even after confirming; a suspended account is locked out.
- **Staff override is governed, not a backdoor** — only the `staff` role can waive the standing gate; it never touches a charge; every waiver is logged with `override: true` and a cited reason.
- **Rules at the connector, not just the prompt** — ownership on cancel, guest-pass allotment, double-booking, dining capacity, clinic spots, lane counts, taken cabanas.
- **PII redacted** before anything enters the audit trail.
- **Human agency preserved** — the ARC request is drafted only; submission stays with the member.

---

## Repo map

```
viba_concierge/
  mcp_servers/
    connectors.py     20 domain tools + side-effect registry (one source of truth)
    serve.py          six FastMCP servers over the same connectors
    seed_data.py      8 seeded members + systems of record + governing docs
  core/                          <- rule-based engine (runs with no API key)
    orchestrator.py   decompose -> delegate -> aggregate -> gate -> commit
    domains.py        six sub-agent handlers (propose, cite, never commit)
    policy.py         PolicyEngine: gates, never-auto-charge, standing/entitlement, staff override, PII redaction, audit
    member_profile.py MemberMemory: shared member profile + session memory
    governing_docs.py TF-IDF retrieval with citations over CC&Rs and rules
    logging.py        structured JSON logs, trace propagation, timing spans
  agents/                        <- Gemini (ADK) integration wrappers
    adk_app.py        ADK root LlmAgent + sub-agents + guardrail callback
    live.py           live Gemini run + structured trace capture
notebooks/
  eleanor_walkthrough.ipynb      data-flow walk-through + eval metrics + audit logs
scripts/
  demo.py             CLI anchor demo: Eleanor's Saturday, end to end
  webapp.py           stdlib web surface over the same orchestrator
tests/test_viba.py    39 tests: security boundaries + full-flow outcomes
SUBMISSION_WRITEUP.md   Kaggle writeup   ·   DEMO_VIDEO_SCRIPT.md   video script
DESIGN.md · IMPLEMENTATION_PLAN.md   rationale, data flow, rubric-mapped plan
```
