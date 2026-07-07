"""Domain connectors: the business-rule layer over the systems of record.

Each connector is a set of plain functions (framework-independent) that:
  - the ADK sub-agents wrap as FunctionTools, and
  - the FastMCP servers expose as MCP tools (same functions, one source of truth).

Mutating operations (book/reserve/charge) never execute directly; they are
declared with side_effect=True so the guardrail layer can gate them behind
member confirmation.
"""
from __future__ import annotations

from typing import Any, Callable

from ..observability.logging import get_logger, span
from . import seed_data
from .seed_data import STORE, SATURDAY

log = get_logger("viba.connectors")

# Registry of {tool_name: {"fn": callable, "side_effect": bool, "domain": str}}
TOOL_REGISTRY: dict[str, dict[str, Any]] = {}


def tool(domain: str, side_effect: bool = False) -> Callable:
    """Register a connector function in the shared tool registry."""
    def deco(fn: Callable) -> Callable:
        TOOL_REGISTRY[fn.__name__] = {"fn": fn, "side_effect": side_effect, "domain": domain}
        return fn
    return deco


def _member(member_id: str) -> dict:
    member = STORE["members"].get(member_id)
    if member is None:
        raise ValueError(f"unknown member_id {member_id}")
    return member


# ----------------------------- golf-teesheet ------------------------------

@tool("golf")
def list_tee_times(day: str = SATURDAY, players: int = 4) -> list[dict]:
    """List open tee times for a day with at least `players` open slots."""
    with span("golf.list_tee_times", domain="golf"):
        sheet = STORE["golf_teesheet"].get(day, {})
        return [
            {"day": day, "time": t, "open_slots": info["slots"]}
            for t, info in sorted(sheet.items())
            if info["booked_by"] is None and info["slots"] >= players
        ]


@tool("golf", side_effect=True)
def book_tee_time(member_id: str, day: str, time: str, players: int) -> dict:
    """Book a tee time for the member and guests. SIDE EFFECT: commits a booking."""
    with span("golf.book_tee_time", domain="golf"):
        sheet = STORE["golf_teesheet"].get(day, {})
        slot = sheet.get(time)
        if slot is None or slot["booked_by"] is not None:
            raise ValueError(f"tee time {day} {time} is not available")
        if players > slot["slots"]:
            raise ValueError(f"only {slot['slots']} slots open at {time}")
        slot["booked_by"] = member_id
        return {"status": "booked", "day": day, "time": time, "players": players}


@tool("golf", side_effect=True)
def cancel_tee_time(member_id: str, day: str, time: str) -> dict:
    """Cancel a tee time the member holds. SIDE EFFECT: frees the slot.

    Only the booking member may cancel their own slot.
    """
    with span("golf.cancel_tee_time", domain="golf"):
        slot = STORE["golf_teesheet"].get(day, {}).get(time)
        if slot is None:
            raise ValueError(f"no tee time at {day} {time}")
        if slot["booked_by"] != member_id:
            raise ValueError("only the booking member may cancel this tee time")
        slot["booked_by"] = None
        return {"status": "cancelled", "day": day, "time": time}


# ---------------------------- racquet-courts ------------------------------

@tool("tennis")
def list_courts(day: str = SATURDAY, start_after: str = "13:00") -> list[dict]:
    """List open court slots on a day, optionally after a start time."""
    with span("tennis.list_courts", domain="tennis"):
        grid = STORE["racquet_courts"].get(day, {})
        out = []
        for court, hours in grid.items():
            for hour, holder in sorted(hours.items()):
                if holder is None and hour >= start_after:
                    out.append({"day": day, "court": court, "time": hour})
        return out


@tool("tennis", side_effect=True)
def reserve_court(member_id: str, day: str, court: str, time: str) -> dict:
    """Reserve a court slot. SIDE EFFECT: commits a reservation."""
    with span("tennis.reserve_court", domain="tennis"):
        grid = STORE["racquet_courts"].get(day, {})
        if grid.get(court, {}).get(time, "x") is not None:
            raise ValueError(f"{court} at {time} on {day} is not available")
        grid[court][time] = member_id
        return {"status": "reserved", "day": day, "court": court, "time": time}


@tool("tennis")
def list_clinics(day: str = SATURDAY) -> list[dict]:
    """List racquet clinics on a day with open spots."""
    with span("tennis.list_clinics", domain="tennis"):
        return [
            {"name": c["name"], "time": c["time"], "spots_open": c["spots_open"]}
            for c in STORE["clinics"].get(day, []) if c["spots_open"] > 0
        ]


@tool("tennis", side_effect=True)
def join_clinic(member_id: str, day: str, clinic_name: str) -> dict:
    """Enroll the member in a racquet clinic. SIDE EFFECT: takes a spot."""
    with span("tennis.join_clinic", domain="tennis"):
        clinic = next((c for c in STORE["clinics"].get(day, [])
                       if c["name"] == clinic_name), None)
        if clinic is None:
            raise ValueError(f"no clinic '{clinic_name}' on {day}")
        if clinic["spots_open"] <= 0:
            raise ValueError(f"clinic '{clinic_name}' is full")
        if member_id in clinic["roster"]:
            raise ValueError("member already enrolled in this clinic")
        clinic["spots_open"] -= 1
        clinic["roster"].append(member_id)
        return {"status": "enrolled", "clinic": clinic_name, "day": day,
                "time": clinic["time"], "spots_open": clinic["spots_open"]}


# ------------------------------- aquatics ---------------------------------

@tool("pool")
def check_guest_pass_eligibility(member_id: str, guest_count: int) -> dict:
    """Verify the member may sponsor `guest_count` pool guests and the cost."""
    with span("pool.check_guest_pass_eligibility", domain="pool"):
        member = _member(member_id)
        ent = member["entitlements"]
        eligible = (
            member["standing"] == "good"
            and guest_count <= ent["guests_per_visit_max"]
            and guest_count <= ent["guest_passes_remaining"]
        )
        return {
            "eligible": eligible,
            "passes_remaining": ent["guest_passes_remaining"],
            "per_visit_max": ent["guests_per_visit_max"],
            "price_each_if_charged": STORE["aquatics"][SATURDAY]["guest_pass_price"],
        }


@tool("pool", side_effect=True)
def issue_guest_passes(member_id: str, guest_names: list[str], day: str = SATURDAY) -> dict:
    """Issue pool guest passes against the member allotment. SIDE EFFECT."""
    with span("pool.issue_guest_passes", domain="pool"):
        member = _member(member_id)
        ent = member["entitlements"]
        unregistered = [g for g in guest_names if g not in member["registered_guests"]]
        if unregistered:
            raise ValueError(f"guests not registered in member profile: {unregistered}")
        if len(guest_names) > ent["guest_passes_remaining"]:
            raise ValueError("insufficient guest passes remaining")
        ent["guest_passes_remaining"] -= len(guest_names)
        return {"status": "issued", "day": day, "guests": guest_names,
                "passes_remaining": ent["guest_passes_remaining"]}


@tool("pool", side_effect=True)
def reserve_lane(member_id: str, day: str = SATURDAY) -> dict:
    """Reserve a lap lane for the member. SIDE EFFECT: takes a lane."""
    with span("pool.reserve_lane", domain="pool"):
        _member(member_id)
        aquatics = STORE["aquatics"].get(day, {})
        if aquatics.get("lap_lanes_open", 0) <= 0:
            raise ValueError(f"no lap lanes open on {day}")
        aquatics["lap_lanes_open"] -= 1
        return {"status": "reserved", "day": day,
                "lap_lanes_open": aquatics["lap_lanes_open"]}


@tool("pool", side_effect=True)
def reserve_cabana(member_id: str, cabana: str, day: str = SATURDAY) -> dict:
    """Reserve a poolside cabana. SIDE EFFECT: assigns the cabana."""
    with span("pool.reserve_cabana", domain="pool"):
        _member(member_id)
        cabanas = STORE["aquatics"].get(day, {}).get("cabanas", {})
        if cabana not in cabanas:
            raise ValueError(f"unknown cabana '{cabana}'")
        if cabanas[cabana] is not None:
            raise ValueError(f"cabana {cabana} is already reserved")
        cabanas[cabana] = member_id
        return {"status": "reserved", "day": day, "cabana": cabana}


# -------------------------------- marina ----------------------------------

@tool("marina")
def list_launch_windows(member_id: str, day: str = SATURDAY) -> dict:
    """List available sunset launch windows for the member's slip."""
    with span("marina.list_launch_windows", domain="marina"):
        member = _member(member_id)
        slip = member["preferences"].get("marina", "")
        return {"slip_note": slip,
                "windows": STORE["marina"]["launch_windows"].get(day, [])}


@tool("marina", side_effect=True)
def schedule_launch(member_id: str, day: str, time: str, passengers: list[str]) -> dict:
    """Schedule a vessel launch and log passengers. SIDE EFFECT."""
    with span("marina.schedule_launch", domain="marina"):
        windows = STORE["marina"]["launch_windows"].get(day, [])
        if time not in windows:
            raise ValueError(f"no launch window at {time} on {day}")
        windows.remove(time)
        return {"status": "scheduled", "day": day, "time": time,
                "passenger_log": passengers}


@tool("marina", side_effect=True)
def log_fuel(member_id: str, gallons: float, day: str = SATURDAY) -> dict:
    """Log a fuel purchase; charges post to the member folio (marina-2.2).
    SIDE EFFECT: money moves, so this is a charge tool."""
    with span("marina.log_fuel", domain="marina"):
        member = _member(member_id)
        price = STORE["marina"]["fuel_price_per_gal"]
        amount = round(gallons * price, 2)
        entry = {"folio_id": member["payment"]["folio_id"],
                 "gallons": gallons, "amount": amount, "memo": "marina fuel"}
        STORE["marina"]["fuel_charges"].append(entry)
        return {"status": "charged", **entry}


# -------------------------------- dining ----------------------------------

@tool("dining")
def get_menu(venue: str, day: str = SATURDAY) -> list[dict]:
    """Return the current menu for a venue."""
    with span("dining.get_menu", domain="dining"):
        return list(STORE["dining"].get("menu", {}).get(venue, []))


@tool("dining")
def check_dining_availability(venue: str, day: str = SATURDAY, party_size: int = 4) -> list[dict]:
    """List reservation times at a venue with capacity for the party."""
    with span("dining.check_availability", domain="dining"):
        slots = STORE["dining"]["venues"].get(venue, {}).get(day, {})
        return [
            {"venue": venue, "day": day, "time": t, "covers_open": n}
            for t, n in sorted(slots.items()) if n >= party_size
        ]


@tool("dining", side_effect=True)
def reserve_table(member_id: str, venue: str, day: str, time: str,
                  party_size: int, notes: str = "") -> dict:
    """Reserve a table; notes carry seating and dietary preferences. SIDE EFFECT."""
    with span("dining.reserve_table", domain="dining"):
        slots = STORE["dining"]["venues"].get(venue, {}).get(day, {})
        if slots.get(time, 0) < party_size:
            raise ValueError(f"{venue} cannot seat {party_size} at {time}")
        slots[time] -= party_size
        return {"status": "reserved", "venue": venue, "day": day,
                "time": time, "party_size": party_size, "notes": notes}


@tool("dining", side_effect=True)
def charge_folio(member_id: str, amount: float, memo: str) -> dict:
    """Post a charge to the member folio. SIDE EFFECT: money moves."""
    with span("dining.charge_folio", domain="dining"):
        member = _member(member_id)
        entry = {"folio_id": member["payment"]["folio_id"],
                 "amount": round(amount, 2), "memo": memo}
        STORE["dining"]["folio_charges"].append(entry)
        return {"status": "charged", **entry}


# --------------------------------- hoa ------------------------------------

@tool("hoa")
def get_dues_status(member_id: str) -> dict:
    """Return the member's HOA dues balance and standing."""
    with span("hoa.get_dues_status", domain="hoa"):
        member = _member(member_id)
        dues = STORE["hoa"]["dues"].get(member_id, {})
        return {"standing": member["standing"], **dues}


@tool("hoa", side_effect=True)
def draft_arc_request(member_id: str, modification: str, details: str) -> dict:
    """Draft (never submit) an Architectural Review Committee request. SIDE EFFECT:
    creates a draft record the member must review and submit themselves."""
    with span("hoa.draft_arc_request", domain="hoa"):
        draft = {"member_id": member_id, "modification": modification,
                 "details": details, "status": "DRAFT - not submitted"}
        STORE["hoa"]["arc_requests"].append(draft)
        return draft


def tools_for_domain(domain: str) -> list[Callable]:
    return [meta["fn"] for meta in TOOL_REGISTRY.values() if meta["domain"] == domain]


def is_side_effect(tool_name: str) -> bool:
    meta = TOOL_REGISTRY.get(tool_name)
    return bool(meta and meta["side_effect"])
