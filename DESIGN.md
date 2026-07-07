# Viba Club Concierge: Design

## Problem

A luxury community is fragmented across six systems (tee sheet, court grid, aquatics registry, marina ledger, dining POS, HOA portal), each with its own login and ruleset. A member's natural request ("Plan Saturday for me and three guests...") spans all six. The product is the orchestration: decompose, reason over availability and entitlements and governing documents, chain the actions, and confirm with the member before anything is booked or charged. A booking form could never span it.

## Architecture (layer by layer, matching the diagram)

```
01 Member surface      Concierge web app (streaming NL)
02 Orchestration       viba-concierge root agent + shared member memory
03 Guardrails          PolicyEngine: every delegation and action passes through
04 Domain sub-agents   golf, dining, tennis, marina, pool, hoa
05 Tool layer          6 MCP servers (FastMCP, stdio)
06 Systems of record   mocked, seeded, deterministic
```

## Key decisions

### 1. One tool registry, two transports
Connector functions in `mcp_servers/connectors.py` are plain Python, registered with a `@tool(domain, side_effect=...)` decorator. ADK sub-agents wrap them as FunctionTools; FastMCP servers expose the same functions over MCP. No code fork between local and MCP deployment, and the side-effect classification travels with the function, which is what the guardrails key on.

### 2. Guardrails as a chokepoint, not a suggestion
`PolicyEngine.check()` runs before every tool execution, in both modes:
- Dry-run mode: `guarded_call()` is the only way handlers and the orchestrator reach a tool.
- Live ADK mode: the same engine is attached as `before_tool_callback` on the root agent and every sub-agent; returning a dict short-circuits the tool, so no model output can route around it.

Order of checks: unknown tool (deny), unknown member (deny), standing (deny, CC&R 9.1), entitlement (deny), side effect without confirmation (needs_confirmation). Charge tools (`charge_folio`, `issue_guest_passes`) carry an explicit never-auto-charge reason. Confirmation is per session and recorded; the audit log captures every verdict with PII-redacted arguments.

### 3. Propose then commit (two-phase itinerary)
Sub-agents only READ and PROPOSE. Proposals are `ItineraryItem`s in shared session memory carrying the exact side-effect tool and args that would commit them. The orchestrator policy-checks each proposed action during the propose phase so the audit trail visibly records the pause (NEEDS_CONFIRMATION rows) before the member ever answers. On approval, `commit()` unlocks the session and executes each item through the same guarded path; on decline, zero side effects, provable from the seeded store.

### 4. Shared member memory as the coordination surface
`MemberMemory` fronts the member record (profile, preferences, registered guests, entitlements, consent flags) plus `SessionMemory` (raw request, decomposed intents, itinerary, cross-agent notes). Sub-agents read preferences to shape proposals (morning tee times, window table, slip B-07) and write findings (guest eligibility, ARC palette rule) that the orchestrator folds into the single member-facing answer. Confirmed actions append to history.

### 5. RAG with mandatory citations
Governing docs (CC&Rs, club rules, marina rules) are retrieved via deterministic TF-IDF cosine similarity behind a `Retriever` protocol; production swaps in embeddings without touching agents. Retrieval returns `Citation` objects and agents attach `[doc-id]` cites to every policy claim, so "can my guests use the pool" and "am I allowed to paint my door navy" are grounded, not guessed. The HOA agent drafts the ARC request but never submits: human agency is preserved on governance actions.

### 6. Observability as a first-class layer
Structured JSON logs with contextvar-propagated `trace_id` and `agent` fields; `span` context managers emit start/end with duration_ms and full exception context on error. One member request is one trace, followable across orchestrator, six sub-agents, guardrail verdicts, and tool calls. This caught two real bugs during the build (a LogRecord key collision and a decomposition gap) purely from the error logs, which is the point.

### 7. Deterministic core, LLM shell
The decompose/delegate/aggregate/confirm/commit pipeline runs without any API key (regex decomposer, rule-based handlers), which makes it fully testable and gives live mode a regression baseline. `adk_app.py` swaps the decomposer and handlers for Gemini LlmAgents while keeping guardrails, memory, tools, RAG, and audit identical. The LLM improves the interface; it cannot weaken the invariants.

## Security and responsible AI

- Never auto-charge: hard rule in the policy engine, independent of model behavior
- Confirmation gates on all side effects; approval is explicit, per session, and audited
- Standing and entitlement checks derived from governing documents, cited
- PII (cards, SSNs, emails, residence) redacted before anything enters the audit trail
- Registered-guest rule enforced at the connector, not just the prompt
- ARC requests are drafted only; submission stays with the member
- Outcome-based tests assert these boundaries on state, not on mocks

## Data flow: Eleanor's request

1. Request arrives; trace_id assigned; standing gate evaluated
2. Decomposed into 6 intents; delegated to 6 sub-agents over shared memory
3. Each sub-agent reads availability (guarded), consults RAG where policy is implicated, and proposes an itinerary item
4. Orchestrator aggregates 6 proposals plus findings; policy records NEEDS_CONFIRMATION for each pending side effect; presentation pauses at the gate
5. Member approves: session unlocked, each action commits through the guarded path, history appended, audit finalized. Member declines: itinerary discarded, store provably untouched
