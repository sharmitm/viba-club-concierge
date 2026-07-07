"""Shared member profile & memory.

One read/write store shared by the orchestrator and every sub-agent:
  - profile:      identity, entitlements, standing, registered guests
  - preferences:  learned + declared per-domain preferences
  - session:      working memory for the current request (decomposed intents,
                  proposed itinerary items, pending confirmations)
  - history:      bookings and charges appended after confirmed actions

Consent flags are honored on every read that leaves the trusted boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..mcp_servers.seed_data import STORE
from ..observability.logging import get_logger, log_event

log = get_logger("viba.memory")


@dataclass
class ItineraryItem:
    intent: str                 # e.g. "morning golf, 4 players"
    domain: str
    tool: str                   # side-effect tool that will commit it
    args: dict[str, Any]
    proposal: str               # human-readable line for the member
    status: str = "proposed"    # proposed | confirmed | committed | declined | failed
    result: Any = None
    # Editable alternatives the member can pick before confirming, keyed by arg:
    #   {"clinic_name": [{"value": "...", "label": "..."}], ...}
    choices: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionMemory:
    member_id: str
    raw_request: str = ""
    intents: list[str] = field(default_factory=list)
    itinerary: list[ItineraryItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # cross-agent findings (RAG cites, eligibility)

    def add_item(self, item: ItineraryItem) -> None:
        self.itinerary.append(item)
        log_event(log, "memory.itinerary_item_added",
                  domain=item.domain, tool=item.tool, intent=item.intent)

    def pending(self) -> list[ItineraryItem]:
        return [i for i in self.itinerary if i.status == "proposed"]


class MemberMemory:
    """Facade over the member record in the system of record + session memory."""

    def __init__(self, member_id: str) -> None:
        if member_id not in STORE["members"]:
            raise ValueError(f"unknown member {member_id}")
        self.member_id = member_id
        self.session = SessionMemory(member_id=member_id)

    @property
    def profile(self) -> dict:
        return STORE["members"][self.member_id]

    def preference(self, domain: str) -> str:
        return self.profile["preferences"].get(domain, "")

    def registered_guests(self) -> list[str]:
        return list(self.profile["registered_guests"])

    def entitlement(self, key: str) -> Any:
        return self.profile["entitlements"].get(key)

    def append_history(self, entry: dict) -> None:
        self.profile.setdefault("history", []).append(entry)
        log_event(log, "memory.history_appended", entry_type=entry.get("type", "?"))

    def consent(self, flag: str) -> bool:
        return bool(self.profile.get("consent", {}).get(flag, False))
