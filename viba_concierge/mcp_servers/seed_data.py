"""Seeded mock systems of record for the six Viba Club domains.

Deterministic in-memory data so the demo, tests, and MCP servers behave
identically on every run. Each 'system' is a plain dict store; the MCP
connector modules layer business rules on top.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta

SATURDAY = (date.today() + timedelta(days=(5 - date.today().weekday()) % 7 or 7)).isoformat()
SUNDAY = (date.today() + timedelta(days=(6 - date.today().weekday()) % 7 or 7)).isoformat()

_SEED = {
    "members": {
        "M-1014": {
            "member_id": "M-1014",
            "name": "Eleanor R.",
            "residence": "Villa 14",
            "tier": "Platinum",
            "standing": "good",           # good | delinquent | suspended
            "dues_current": True,
            "handicap": 14.2,
            "registered_guests": ["Priya S.", "Daniel K.", "Maya L."],
            "entitlements": {
                "golf": True, "tennis": True, "pool": True,
                "marina": True, "dining": True,
                "guest_passes_remaining": 6,
                "guests_per_visit_max": 3,
            },
            "payment": {"folio_id": "F-1014", "card_last4": "4321"},
            "preferences": {
                "golf": "prefers morning tee times, walking with caddie",
                "dining": "window table, no shellfish for one guest",
                "marina": "own vessel 'Second Wind', slip B-07",
            },
            "consent": {"share_activity_with_household": True, "marketing": False},
        },
        "M-2201": {
            "member_id": "M-2201",
            "name": "Marcus T.",
            "residence": "Villa 22",
            "tier": "Gold",
            "standing": "delinquent",     # dues in arrears -> booking privileges suspended
            "dues_current": False,
            "handicap": 9.5,
            "registered_guests": ["Nadia T."],
            "entitlements": {
                "golf": True, "tennis": True, "pool": True,
                "marina": False, "dining": True,
                "guest_passes_remaining": 4,
                "guests_per_visit_max": 2,
            },
            "payment": {"folio_id": "F-2201", "card_last4": "7788"},
            "preferences": {
                "golf": "prefers afternoon rounds",
                "dining": "chef's counter, no nuts",
            },
            "consent": {"share_activity_with_household": False, "marketing": True},
        },
        "M-3310": {
            "member_id": "M-3310", "name": "Priya N.", "residence": "Villa 33",
            "tier": "Silver", "standing": "good", "dues_current": True, "handicap": 21.8,
            "registered_guests": ["Anil N."],
            "entitlements": {"golf": True, "tennis": True, "pool": True, "marina": False,
                             "dining": True, "guest_passes_remaining": 3, "guests_per_visit_max": 2},
            "payment": {"folio_id": "F-3310", "card_last4": "1102"},
            "preferences": {"golf": "early riser, prefers walking", "dining": "no shellfish"},
            "consent": {"share_activity_with_household": True, "marketing": True},
        },
        "M-1188": {
            "member_id": "M-1188", "name": "Daniel K.", "residence": "Villa 11",
            "tier": "Gold", "standing": "good", "dues_current": True, "handicap": 8.1,
            "registered_guests": ["Elise K.", "Tom R."],
            "entitlements": {"golf": True, "tennis": True, "pool": True, "marina": True,
                             "dining": True, "guest_passes_remaining": 5, "guests_per_visit_max": 3},
            "payment": {"folio_id": "F-1188", "card_last4": "6650"},
            "preferences": {"tennis": "clay courts, morning clinics", "golf": "prefers a cart"},
            "consent": {"share_activity_with_household": True, "marketing": False},
        },
        "M-4402": {
            "member_id": "M-4402", "name": "Sofia L.", "residence": "Villa 44",
            "tier": "Platinum", "standing": "good", "dues_current": True, "handicap": 15.6,
            "registered_guests": ["Marco L.", "Bianca L.", "Guest of Sofia"],
            "entitlements": {"golf": True, "tennis": True, "pool": True, "marina": True,
                             "dining": True, "guest_passes_remaining": 6, "guests_per_visit_max": 4},
            "payment": {"folio_id": "F-4402", "card_last4": "3390"},
            "preferences": {"dining": "vegetarian, quiet table", "marina": "slip C-12, vessel 'Adriatic'"},
            "consent": {"share_activity_with_household": True, "marketing": True},
        },
        "M-5150": {
            "member_id": "M-5150", "name": "James O.", "residence": "Villa 51",
            "tier": "Silver", "standing": "suspended", "dues_current": False, "handicap": 12.4,
            "registered_guests": [],
            "entitlements": {"golf": True, "tennis": False, "pool": True, "marina": False,
                             "dining": True, "guest_passes_remaining": 2, "guests_per_visit_max": 2},
            "payment": {"folio_id": "F-5150", "card_last4": "8811"},
            "preferences": {"golf": "twilight rounds"},
            "consent": {"share_activity_with_household": False, "marketing": False},
        },
        "M-2760": {
            "member_id": "M-2760", "name": "Aisha B.", "residence": "Villa 27",
            "tier": "Gold", "standing": "good", "dues_current": True, "handicap": 18.9,
            "registered_guests": ["Omar B."],
            "entitlements": {"golf": True, "tennis": True, "pool": True, "marina": False,
                             "dining": True, "guest_passes_remaining": 4, "guests_per_visit_max": 3},
            "payment": {"folio_id": "F-2760", "card_last4": "2247"},
            "preferences": {"pool": "poolside cabana", "dining": "chef's tasting menu"},
            "consent": {"share_activity_with_household": True, "marketing": True},
        },
        "M-3021": {
            "member_id": "M-3021", "name": "Ravi S.", "residence": "Villa 30",
            "tier": "Platinum", "standing": "good", "dues_current": True, "handicap": 6.3,
            "registered_guests": ["Meera S.", "Kiran S."],
            "entitlements": {"golf": True, "tennis": True, "pool": True, "marina": True,
                             "dining": True, "guest_passes_remaining": 6, "guests_per_visit_max": 4},
            "payment": {"folio_id": "F-3021", "card_last4": "9004"},
            "preferences": {"golf": "afternoon rounds, low handicap group", "marina": "sunset cruises"},
            "consent": {"share_activity_with_household": True, "marketing": False},
        },
    },
    "golf_teesheet": {
        SATURDAY: {
            "07:40": {"slots": 4, "booked_by": None},
            "08:10": {"slots": 4, "booked_by": None},
            "08:50": {"slots": 2, "booked_by": "M-3310"},   # Priya (Silver — golf is included)
            "09:30": {"slots": 4, "booked_by": "M-2201"},
        }
    },
    "racquet_courts": {
        SATURDAY: {
            "court-1": {"14:00": None, "15:00": None, "16:00": "M-2760"},   # Aisha (Gold — has tennis)
            "court-2": {"14:00": None, "15:00": "M-1188", "16:00": None},
            "pickle-1": {"14:00": None, "15:00": None, "16:00": None},
        }
    },
    "clinics": {
        SATURDAY: [
            {"name": "Cardio Tennis", "time": "10:00", "spots_open": 3, "roster": ["M-3021"]},
            {"name": "Junior Pickleball", "time": "11:00", "spots_open": 5, "roster": ["M-1188"]},
        ]
    },
    "aquatics": {
        SATURDAY: {
            "lap_lanes_open": 3,
            "cabanas": {"C1": None, "C2": "M-2760", "C3": "M-4402"},
            "guest_pass_price": 15.00,
        }
    },
    "marina": {
        "slips": {"B-07": {"vessel": "Second Wind", "owner": "M-1014"}},
        "launch_windows": {SATURDAY: ["17:30", "18:00", "18:30"]},
        "fuel_price_per_gal": 5.85,
        "fuel_charges": [],
    },
    "dining": {
        "venues": {
            "The Grill": {
                SATURDAY: {"12:00": 6, "12:30": 4, "13:00": 0},  # remaining covers
            }
        },
        "menu": {
            "The Grill": [
                {"item": "Club Cobb Salad", "price": 22.0},
                {"item": "Wagyu Burger", "price": 28.0},
                {"item": "Grilled Branzino", "price": 34.0},
            ]
        },
        "folio_charges": [],
    },
    "hoa": {
        "dues": {
            "M-1014": {"balance": 0.00, "next_due": "2026-08-01"},
            "M-2201": {"balance": 420.00, "next_due": "2026-06-01"},   # in arrears
            "M-3310": {"balance": 0.00, "next_due": "2026-08-01"},
            "M-1188": {"balance": 0.00, "next_due": "2026-08-01"},
            "M-4402": {"balance": 0.00, "next_due": "2026-08-01"},
            "M-5150": {"balance": 180.00, "next_due": "2026-06-15"},   # in arrears
            "M-2760": {"balance": 0.00, "next_due": "2026-08-01"},
            "M-3021": {"balance": 0.00, "next_due": "2026-08-01"},
        },
        "arc_requests": [],
    },
}

# Governing documents corpus for RAG (HOA CC&Rs, club rules).
GOVERNING_DOCS = [
    {
        "doc_id": "ccr-4.2",
        "title": "CC&R Section 4.2 - Exterior Modifications",
        "text": (
            "No owner shall alter the exterior appearance of any dwelling, including "
            "paint color of doors, trim, or siding, without prior written approval of "
            "the Architectural Review Committee (ARC). Applications must include the "
            "proposed color swatch and manufacturer code. Pre-approved door palette: "
            "Estate White, Forest Green, Classic Navy (Sherwin-Williams SW 6244), and "
            "Charleston Black. Colors on the pre-approved palette receive expedited "
            "review within five business days."
        ),
    },
    {
        "doc_id": "club-7.1",
        "title": "Club Rules 7.1 - Guest Privileges",
        "text": (
            "Members in good standing may sponsor up to three accompanied guests per "
            "visit. Guest access to the aquatics center requires a guest pass, "
            "deducted from the member's annual allotment or charged to the member "
            "folio. Guests must be registered in the member profile prior to arrival. "
            "Unaccompanied guests are not permitted in any facility."
        ),
    },
    {
        "doc_id": "club-3.4",
        "title": "Club Rules 3.4 - Golf Guest Policy",
        "text": (
            "Guests may play golf when accompanied by a sponsoring member. Guest "
            "green fees are charged to the member folio at the prevailing rate. "
            "Morning tee times before 09:00 on weekends are reserved for members "
            "and their accompanied guests only."
        ),
    },
    {
        "doc_id": "marina-2.2",
        "title": "Marina Rules 2.2 - Vessel Operations",
        "text": (
            "Slip holders may schedule sunset launches with a minimum two-hour "
            "notice. All passengers must be logged for Coast Guard compliance. "
            "Fuel charges post to the member folio. Guests aboard member vessels "
            "do not require separate marina passes."
        ),
    },
    {
        "doc_id": "ccr-9.1",
        "title": "CC&R Section 9.1 - Dues and Standing",
        "text": (
            "A member whose dues are more than thirty days in arrears is not in "
            "good standing and forfeits booking privileges and guest sponsorship "
            "until the balance is cured."
        ),
    },
]


# Membership tiers — the single source of truth for what each tier includes.
# Facility access, guest-pass allotment, per-visit guests and booking window all
# escalate Silver -> Gold -> Platinum. Every member's entitlements are DERIVED
# from their tier at load, so the three tiers are consistently different and no
# member can silently drift from their tier's benefits.
TIER_BENEFITS = {
    # weekend_days: which weekend days the tier may book. Weekend access escalates
    # Silver (weekdays only) -> Gold (+ Saturday) -> Platinum (+ Sunday).
    "Silver":   {"facilities": ("golf", "pool", "dining"),
                 "annual_passes": 2, "guests_per_visit_max": 2, "weekend_days": ()},
    "Gold":     {"facilities": ("golf", "tennis", "pool", "dining"),
                 "annual_passes": 4, "guests_per_visit_max": 3, "weekend_days": ("Saturday",)},
    "Platinum": {"facilities": ("golf", "tennis", "pool", "marina", "dining"),
                 "annual_passes": 6, "guests_per_visit_max": 4,
                 "weekend_days": ("Saturday", "Sunday")},
}
_ALL_FACILITIES = ("golf", "tennis", "pool", "marina", "dining")


def tier_entitlements(tier: str, remaining: int | None = None) -> dict:
    """Facility access + guest-pass limits for a tier. `remaining` is the member's
    current pass balance (clamped to the tier allotment); defaults to a full allotment."""
    b = TIER_BENEFITS[tier]
    rem = b["annual_passes"] if remaining is None else min(remaining, b["annual_passes"])
    ent = {f: (f in b["facilities"]) for f in _ALL_FACILITIES}
    ent["guest_passes_remaining"] = rem
    ent["guests_per_visit_max"] = b["guests_per_visit_max"]
    return ent


def _add_days(store: dict) -> None:
    """Populate availability for the upcoming days so members can book any date.
    Saturday keeps its pre-seeded bookings; every other day starts freshly open.
    Weekend-day access is gated per tier in the policy layer."""
    gt, rc = store["golf_teesheet"], store["racquet_courts"]
    cl, aq = store["clinics"], store["aquatics"]
    mar, din = store["marina"]["launch_windows"], store["dining"]["venues"]
    golf_t, court_t, clinic_t = gt[SATURDAY], rc[SATURDAY], cl[SATURDAY]
    aq_t, mar_t = aq[SATURDAY], mar[SATURDAY]
    for i in range(1, 15):
        d = (date.today() + timedelta(days=i)).isoformat()
        if d == SATURDAY:
            continue
        gt.setdefault(d, {t: {"slots": info["slots"], "booked_by": None}
                          for t, info in golf_t.items()})
        rc.setdefault(d, {c: {h: None for h in hours} for c, hours in court_t.items()})
        cl.setdefault(d, [{"name": c["name"], "time": c["time"],
                           "spots_open": c["spots_open"] + len(c["roster"]), "roster": []}
                          for c in clinic_t])
        aq.setdefault(d, {"lap_lanes_open": aq_t["lap_lanes_open"],
                          "cabanas": {k: None for k in aq_t["cabanas"]},
                          "guest_pass_price": aq_t["guest_pass_price"]})
        mar.setdefault(d, list(mar_t))
        for days in din.values():
            days.setdefault(d, dict(days[SATURDAY]))


def fresh_store() -> dict:
    """Isolated deep copy of the seed, with every member's entitlements normalized
    to their tier (TIER_BENEFITS is authoritative) and Sunday availability added."""
    store = copy.deepcopy(_SEED)
    for member in store["members"].values():
        prior = member.get("entitlements", {}).get("guest_passes_remaining")
        member["entitlements"] = tier_entitlements(member["tier"], prior)
    _add_days(store)
    return store


# Module-level shared store used by the live demo / MCP servers.
STORE = fresh_store()


def reset_store() -> None:
    global STORE
    STORE.clear()
    STORE.update(fresh_store())
