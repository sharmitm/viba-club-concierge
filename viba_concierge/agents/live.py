"""Live ADK mode: run the Gemini-powered root agent and capture its trace.

Unlike the deterministic dry-run pipeline, here Gemini performs the intent
decomposition, decides which sub-agents and tools to call, and aggregates the
result. The SAME guardrail layer (adk_app._guardrail_before_tool) intercepts
every side-effect tool, so nothing books or charges until the member confirms.

Two turns model the confirmation gate:
  live_propose(request) -> agent proposes; side-effect tools are gated
  live_confirm(sid, ok) -> on approval the agent calls confirm_itinerary and
                           re-runs the booking tools, now allowed

Requires GOOGLE_API_KEY. Everything is captured as a structured trace of
{type: text|tool_call|tool_result|gate, agent, ...} so the web UI can show
exactly what the model reasoned and attempted.
"""
from __future__ import annotations

import asyncio
import os
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ..core.policy import PolicyEngine
from ..mcp_servers.seed_data import reset_store
from . import adk_app

APP_NAME = "viba-concierge"
USER_ID = "M-1014"

_session_service = InMemorySessionService()
_runner = Runner(agent=adk_app.root_agent, app_name=APP_NAME,
                 session_service=_session_service)


class LiveModeError(RuntimeError):
    """Raised when live mode can't run (e.g. missing API key)."""


def _require_key() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        raise LiveModeError(
            "GOOGLE_API_KEY is not set. Add it to viba-concierge/.env "
            "(GOOGLE_API_KEY=...) and restart the server to use live mode.")


def _collect(event, trace: list[dict]) -> None:
    """Turn one ADK event into trace rows the UI can render."""
    content = getattr(event, "content", None)
    if not content or not getattr(content, "parts", None):
        return
    author = getattr(event, "author", None) or "agent"
    for part in content.parts:
        fc = getattr(part, "function_call", None)
        fr = getattr(part, "function_response", None)
        text = getattr(part, "text", None)
        if fc:
            trace.append({"type": "tool_call", "agent": author,
                          "tool": fc.name, "args": dict(fc.args or {})})
        elif fr:
            resp = fr.response
            gated = isinstance(resp, dict) and resp.get("blocked")
            trace.append({"type": "gate" if gated else "tool_result",
                          "agent": author, "tool": fr.name, "response": resp})
        elif text and text.strip():
            trace.append({"type": "text", "agent": author, "text": text.strip()})


async def _arun(user_id: str, session_id: str, message: str,
                trace: list[dict], create: bool) -> None:
    if create:
        await _session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id)
    async for event in _runner.run_async(
            user_id=user_id, session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)])):
        _collect(event, trace)


def _member_preamble(member: dict) -> str:
    return (f"You are serving club member {member['name']} (member_id "
            f"'{member['id']}', {member.get('tier','')} tier, "
            f"{member.get('standing','good')} standing). Use member_id="
            f"'{member['id']}' for every tool call.\n\n")


def live_propose(request: str, member: dict) -> dict:
    """First turn: fresh state, agent proposes, side-effects are gated."""
    _require_key()
    reset_store()
    adk_app._policy = PolicyEngine()   # module global; callback reads it live
    session_id = uuid.uuid4().hex[:12]
    trace: list[dict] = []
    asyncio.run(_arun(member["id"], session_id,
                      _member_preamble(member) + request, trace, create=True))
    return {"session_id": session_id, "trace": trace}


def live_confirm(session_id: str, approved: bool, member: dict) -> dict:
    """Second turn: member's decision at the gate.

    The member's click IS the confirmation, so we record it on the policy
    engine deterministically (never relying on the model to call a tool) —
    mirroring how the dry-run orchestrator.commit() calls confirm_itinerary().
    Only then do the now-unlocked booking tools execute.
    """
    _require_key()
    if approved:
        adk_app._policy.confirm_itinerary()   # deterministic gate lift
    trace: list[dict] = []
    message = ("I confirm — please book the full itinerary now."
               if approved else
               "No, do not book anything. Cancel the itinerary.")
    asyncio.run(_arun(member["id"], session_id, message, trace, create=False))
    return {"session_id": session_id, "trace": trace, "approved": approved}
