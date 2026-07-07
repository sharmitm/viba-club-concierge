# Viba Club Concierge: Implementation Plan

Capstone target: Google x Kaggle AI Agents Intensive Vibe Coding Capstone (Concierge track).
Scope: two weeks. Back ends are mocked with seeded data; the build is the agent logic, the guardrail layer, and the orchestration.

## Course concepts to demonstrate (rubric mapping)

| Concept | Where it lives | Proof in demo |
|---|---|---|
| Multi-agent orchestration (ADK) | `agents/orchestrator.py`, `agents/adk_app.py` (root LlmAgent + 6 sub-agents) | One request fans out to six sub-agents, reconciled into one itinerary |
| MCP tool servers | `mcp_servers/serve.py` (6 FastMCP servers), `mcp_servers/connectors.py` | Each domain exposes list/book/cancel tools over MCP stdio |
| RAG over governing docs | `rag/governing_docs.py` | "Can I paint my door navy?" answered with a [ccr-4.2] citation |
| Policy and guardrail layer | `guardrails/policy.py` | Audit trail shows NEEDS_CONFIRMATION for every side effect before member approval; charge tools can never auto-fire |
| Shared member memory | `memory/member_profile.py` | Preferences, registered guests, and entitlements shape every sub-agent proposal; history appended after commit |

## Week 1: core system (done in this repo)

Day 1 and 2: Foundations
- Repo scaffold, seeded systems of record for all six clubs (`seed_data.py`)
- Observability first: structured JSON logging with trace_id propagation, timing spans, error capture (`observability/logging.py`)

Day 3 and 4: Tools and guardrails
- Domain connectors with a side-effect registry; one source of truth consumed by both ADK FunctionTools and FastMCP servers
- PolicyEngine: entitlement checks, standing gate (CC&R 9.1), confirmation gates, never-auto-charge, PII redaction, audit log

Day 5 and 6: Agents
- Six domain sub-agent handlers (propose, cite, never commit)
- Orchestrator pipeline: decompose, delegate, aggregate, pause at the gate, commit on approval
- RAG retriever over governing docs with citation objects

Day 7: Quality gate
- 23 outcome-based tests covering security boundaries, state mutations, and the full flow (approve and decline paths)
- Demo script producing the 90-second anchor story deterministically

## Week 2: live mode, UI, submission

Day 8 and 9: Live ADK mode
- `agents/adk_app.py` is already wired: Gemini root agent, six LlmAgent sub-agents, guardrail before_tool_callback
- Set GOOGLE_API_KEY, run `adk web viba_concierge/agents`, validate the playground against the demo transcript
- Tune sub-agent instructions until live decomposition matches the deterministic pipeline on Eleanor's request

Day 10: MCP transport in live mode
- Swap FunctionTools for McpToolset(stdio) pointing at `python -m viba_concierge.mcp_servers.serve <domain>` per sub-agent
- Verify the guardrail callback still intercepts (it gates by tool name, transport-independent)

Day 11: Member surface
- Thin web front end (streaming chat) over the ADK Runner; render the itinerary card and the confirmation gate as an explicit approve/decline control
- Never let the UI bypass the gate: approval maps to `confirm_itinerary` only

Day 12: Evaluation and hardening
- `agents-cli eval run` with an evalset built from the test scenarios (happy path, decline, delinquent member, unregistered guest, sold-out venue)
- Load the audit trail into the writeup as the responsible-AI evidence

Day 13: Demo video (90 seconds)
- 0 to 15s: Eleanor's single request, six decomposed intents on screen
- 15 to 45s: sub-agents fan out; live trace log side panel shows spans per domain
- 45 to 70s: itinerary proposed, GATE ACTIVE, audit shows NEEDS_CONFIRMATION rows
- 70 to 90s: member approves; commits stream in; ARC request shown as DRAFT, never submitted

Day 14: Kaggle writeup and submission
- Problem, architecture diagram (the uploaded one), concept mapping table, limitations, next steps

## Risks and mitigations

- LLM decomposition drift in live mode: the deterministic pipeline is the regression baseline; compare intent sets per request
- Guardrail bypass via sub-agent transfer: the before_tool_callback is attached to the root and every sub-agent, and the policy engine gates by tool name, so no path around it
- Demo timing: the dry-run demo is the fallback recording if live latency misbehaves

## Definition of done

- All tests pass; demo runs clean in both approve and decline paths
- Live playground reproduces the anchor scenario with citations
- Video plus writeup submitted with the concept mapping table
