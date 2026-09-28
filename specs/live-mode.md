# Live mode spec (`LV`)

Implementation: `viba_concierge/agents/adk_app.py`. When Gemini agents choose the
tools, the invariants in `GR` MUST still hold; the LLM may improve the interface
but cannot weaken the guardrails. These tests need `google-adk` installed and
are skipped without it.

### LV-01 Guardrail callback gates every registered connector
**Rule.** The ADK `before_tool_callback` (attached to the root agent and every
sub-agent) MUST run `PolicyEngine.check` for every tool in `TOOL_REGISTRY` and
short-circuit anything not `allow` with a `blocked` payload. Framework tools
(e.g. `transfer_to_agent`) and the gate tools (`ask_governing_docs`,
`confirm_itinerary`) pass through.
**Acceptance.**
- Calling the callback for `book_tee_time` before confirmation returns
  `{"blocked": True, "verdict": "needs_confirmation", ...}`.
- Calling it for `transfer_to_agent` returns `None`.
**Status.** enforced

### LV-02 Live decomposition matches the deterministic baseline
**Rule.** For the reference request, the live root agent MUST delegate to the
same six domains the deterministic pipeline produces (`OR-01`).
**Acceptance.**
- An `agents-cli eval` evalset built from the `OR` scenarios passes.
**Status.** planned
