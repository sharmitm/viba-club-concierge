"""ADK 2.x application: viba-concierge root agent + six domain sub-agents.

Live mode (requires GOOGLE_API_KEY): Gemini performs intent decomposition,
delegation via sub-agents, and natural-language aggregation. The SAME
guardrail layer used in dry-run mode is attached as a before_tool_callback,
so side-effect tools pause for confirmation and charges can never fire
without member approval, regardless of what the model decides.

Run the local playground:
    adk web viba_concierge/agents
or programmatically via `build_app()`.
"""
from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from ..core.policy import PolicyEngine, Verdict
from ..mcp_servers import connectors as c
from ..core.logging import get_logger
from ..core.governing_docs import ask_governing_docs

log = get_logger("viba.adk")

MODEL = "gemini-2.5-flash"

# The signed-in member. In production this comes from the authenticated session;
# for the single-member demo we bind it so agents never ask "who are you?".
MEMBER_CONTEXT = (
    "You are serving the signed-in member identified at the start of the "
    "conversation. ALWAYS pass that member_id to any tool that needs it. NEVER "
    "ask the member for their ID, name, or residence — it is already provided. "
)

# One policy engine per process for the playground; the demo/tests construct
# their own per-session engines through ConciergeOrchestrator.
_policy = PolicyEngine()


def confirm_itinerary() -> dict:
    """Record the member's explicit confirmation of the proposed itinerary.
    Call ONLY after the member replies with clear approval (e.g. 'yes, book it')."""
    _policy.confirm_itinerary()
    return {"status": "confirmed", "note": "side-effect tools unlocked for this session"}


def _guardrail_before_tool(tool, args: dict[str, Any], tool_context) -> dict | None:
    """ADK before_tool_callback: enforce policy before ANY tool executes.

    Returning a dict short-circuits the tool call; the model receives the
    verdict and must relay the pause to the member instead of proceeding.
    """
    name = getattr(tool, "name", str(tool))
    if name in {"ask_governing_docs", "confirm_itinerary"}:
        return None  # read-only / gate tools are always allowed
    # Only OUR registered domain connectors are policy-gated. ADK framework
    # tools (e.g. transfer_to_agent for sub-agent delegation) must pass through.
    if name not in c.TOOL_REGISTRY:
        return None
    decision = _policy.check(actor="adk", tool_name=name, args=args)
    if decision.verdict is Verdict.ALLOW:
        return None
    return {
        "blocked": True,
        "verdict": decision.verdict.value,
        "reason": decision.reason,
        "instruction": ("Present the full itinerary to the member and ask for "
                        "confirmation. Do not retry this tool until the member "
                        "approves via confirm_itinerary."),
    }


def _agent(name: str, description: str, domain: str, extra_instr: str = "") -> LlmAgent:
    tools = [FunctionTool(fn) for fn in c.tools_for_domain(domain)]
    tools.append(FunctionTool(ask_governing_docs))
    return LlmAgent(
        name=name,
        model=MODEL,
        description=description,
        instruction=(
            f"You are the {name} for Viba Club. Handle only {domain} tasks. "
            + MEMBER_CONTEXT +
            "First check availability/eligibility with read tools; cite governing "
            "docs via ask_governing_docs for any policy claim. PROPOSE actions; "
            "side-effect tools will be gated until the member confirms. "
            "Never invent availability. " + extra_instr
        ),
        tools=tools,
        before_tool_callback=_guardrail_before_tool,
    )


def build_root_agent() -> LlmAgent:
    subs = [
        _agent("golf_agent", "Tee times, pairings, cart and caddie.", "golf"),
        _agent("dining_agent", "Reservations, banquets, member folio.", "dining",
               "Never call charge_folio unless the member explicitly asked to be charged."),
        _agent("tennis_agent", "Court booking, clinics, ball machine.", "tennis"),
        _agent("marina_agent", "Slip and vessel scheduling, fuel, launch.", "marina"),
        _agent("pool_agent", "Lap lanes, cabanas, guest passes.", "pool",
               "Always verify guest-pass eligibility before proposing passes."),
        _agent("hoa_agent", "Governance, dues, ARC requests.", "hoa",
               "Draft ARC requests only; NEVER submit on the member's behalf."),
    ]
    return LlmAgent(
        name="viba_concierge",
        model=MODEL,
        description="Viba Club member concierge orchestrator.",
        instruction=(
            MEMBER_CONTEXT +
            "You are the Viba Club concierge orchestrator. For EVERY domain in the "
            "member's request you MUST transfer to the matching sub-agent "
            "(golf_agent, dining_agent, tennis_agent, marina_agent, pool_agent, "
            "hoa_agent) so it can call its tools. Transfer to each relevant "
            "sub-agent one at a time until all domains are handled. "
            "You MUST NOT state any tee time, table, court, launch window, guest "
            "pass, or approval from your own knowledge — every detail in your "
            "itinerary must come from a tool result a sub-agent returned. Do not "
            "answer the request directly without delegating. "
            "After the sub-agents have proposed, aggregate their tool-backed "
            "results into ONE itinerary and PAUSE for confirmation before any "
            "booking or charge. Only after the member clearly approves, call "
            "confirm_itinerary and let the sub-agents re-run their booking tools."
        ),
        sub_agents=subs,
        tools=[FunctionTool(confirm_itinerary)],
        before_tool_callback=_guardrail_before_tool,
    )


root_agent = build_root_agent()  # discovered by `adk web` / Agent Runtime
