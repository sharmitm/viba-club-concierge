"""Domain sub-agent handlers.

Each handler receives a delegated intent plus shared member memory and returns
proposed itinerary items. Handlers READ freely through guarded calls but never
COMMIT: side-effect tools are only executed by the orchestrator after the
member confirms, which is what the guardrail layer enforces.
"""
from __future__ import annotations

from ..guardrails.policy import PolicyEngine, guarded_call
from ..memory.member_profile import ItineraryItem, MemberMemory
from ..mcp_servers.seed_data import SATURDAY
from ..observability.logging import current_agent, get_logger, span
from ..rag.governing_docs import ask_governing_docs

log = get_logger("viba.agents")


class DomainHandler:
    name = "base"
    domain = "base"

    def __init__(self, policy: PolicyEngine, memory: MemberMemory):
        self.policy = policy
        self.memory = memory

    def handle(self, intent: str) -> list[ItineraryItem]:
        token = current_agent.set(self.name)
        try:
            with span(f"agent.{self.name}", intent=intent):
                return self._handle(intent)
        finally:
            current_agent.reset(token)

    def _handle(self, intent: str) -> list[ItineraryItem]:  # pragma: no cover
        raise NotImplementedError

    def _read(self, tool: str, **args):
        return guarded_call(self.policy, self.name, tool, **args)

    def _target_day(self) -> str:
        """Resolve the day-of-week named in the request to an upcoming date;
        default to Saturday (the anchor demo day) when none is named."""
        from datetime import date, timedelta
        req = (self.memory.session.raw_request or "").lower()
        weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                    "friday": 4, "saturday": 5, "sunday": 6}
        for name, wd in weekdays.items():
            if name in req:
                ahead = (wd - date.today().weekday()) % 7 or 7
                return (date.today() + timedelta(days=ahead)).isoformat()
        return SATURDAY


class GolfAgent(DomainHandler):
    name, domain = "golf-agent", "golf"

    def _handle(self, intent: str) -> list[ItineraryItem]:
        member_id = self.memory.member_id
        req = (self.memory.session.raw_request or intent).lower()
        day = self._target_day()
        if "cancel" in req:
            from ..mcp_servers.seed_data import STORE
            sheet = STORE["golf_teesheet"].get(day, {})
            slot = next((t for t in sorted(sheet) if sheet[t]["booked_by"] == member_id), None)
            if not slot:
                self.memory.session.notes.append("golf: you have no tee time to cancel that day")
                return []
            return [ItineraryItem(intent=intent, domain=self.domain, tool="cancel_tee_time",
                args={"member_id": member_id, "day": day, "time": slot},
                proposal=f"Cancel your golf tee time at {slot}")]
        if "lesson" in req:
            self.memory.session.notes.append("golf: lessons are arranged through the pro shop")
            return []
        wants_four = any(k in req for k in ("4", "four", "three guests", "3 guests"))
        players = 4 if wants_four else 2
        options = self._read("list_tee_times", day=day, players=players)
        if not options:
            self.memory.session.notes.append("golf: no tee times with enough slots")
            return []
        pref = self.memory.preference("golf")
        pick = options[0]  # earliest open time honors 'prefers morning'
        rules = ask_governing_docs("guest green fees weekend morning tee times")
        cite = rules["citations"][0]["doc_id"] if rules["citations"] else "club-3.4"
        return [ItineraryItem(
            intent=intent, domain=self.domain, tool="book_tee_time",
            args={"member_id": member_id, "day": pick["day"],
                  "time": pick["time"], "players": players},
            proposal=(f"Golf {pick['day']} at {pick['time']} for {players} "
                      f"(pref: {pref}; guest fees per [{cite}])"),
            choices={"time": [{"value": o["time"], "label": f"{o['time']} ({o['open_slots']} slots)"}
                              for o in options]},
        )]


class DiningAgent(DomainHandler):
    name, domain = "dining-agent", "dining"

    def _handle(self, intent: str) -> list[ItineraryItem]:
        member_id = self.memory.member_id
        req = (self.memory.session.raw_request or intent).lower()
        day = self._target_day()
        venue = "The Grill"
        if "menu" in req:
            menu = self._read("get_menu", venue=venue, day=day)
            items = ", ".join(f"{m['item']} ${m['price']:.0f}" for m in menu)
            self.memory.session.notes.append(f"dining: {venue} menu — {items}")
            return []
        options = self._read("check_dining_availability", venue=venue,
                             day=day, party_size=4)
        if not options:
            self.memory.session.notes.append(f"dining: no availability at {venue}")
            return []
        pick = options[0]
        notes = self.memory.preference("dining")
        return [ItineraryItem(
            intent=intent, domain=self.domain, tool="reserve_table",
            args={"member_id": member_id, "venue": venue, "day": pick["day"],
                  "time": pick["time"], "party_size": 4, "notes": notes},
            proposal=f"Lunch at {venue} {pick['day']} {pick['time']}, party of 4 ({notes})",
            choices={"time": [{"value": o["time"], "label": f"{o['time']} ({o['covers_open']} covers)"}
                              for o in options]},
        )]


class TennisAgent(DomainHandler):
    name, domain = "tennis-agent", "tennis"

    def _handle(self, intent: str) -> list[ItineraryItem]:
        member_id = self.memory.member_id
        req = (self.memory.session.raw_request or intent).lower()
        day = self._target_day()
        if "clinic" in req:
            clinics = self._read("list_clinics", day=day)
            if not clinics:
                self.memory.session.notes.append("tennis: no clinics with open spots that day")
                return []
            pick = clinics[0]
            return [ItineraryItem(intent=intent, domain=self.domain, tool="join_clinic",
                args={"member_id": member_id, "day": day, "clinic_name": pick["name"]},
                proposal=f"Join {pick['name']} at {pick['time']} ({pick['spots_open']} spots open)",
                choices={"clinic_name": [
                    {"value": c["name"], "label": f"{c['name']} · {c['time']} ({c['spots_open']} spots)"}
                    for c in clinics]})]
        if "coach" in req or "lesson" in req:
            self.memory.session.notes.append("tennis: private coaching is booked with the tennis pro")
            return []
        options = self._read("list_courts", day=day, start_after="14:00")
        if not options:
            self.memory.session.notes.append("tennis: no afternoon courts open")
            return []
        pick = options[0]
        courts = sorted({o["court"] for o in options})
        times = sorted({o["time"] for o in options})
        return [ItineraryItem(
            intent=intent, domain=self.domain, tool="reserve_court",
            args={"member_id": member_id, "day": pick["day"],
                  "court": pick["court"], "time": pick["time"]},
            proposal=f"Tennis on {pick['court']} at {pick['time']}",
            choices={"court": [{"value": c, "label": c} for c in courts],
                     "time": [{"value": t, "label": t} for t in times]},
        )]


class PoolAgent(DomainHandler):
    name, domain = "pool-agent", "pool"

    def _handle(self, intent: str) -> list[ItineraryItem]:
        member_id = self.memory.member_id
        req = (self.memory.session.raw_request or intent).lower()
        day = self._target_day()
        if "cabana" in req:
            from ..mcp_servers.seed_data import STORE
            cabanas = STORE["aquatics"].get(day, {}).get("cabanas", {})
            free_list = [c for c in sorted(cabanas) if cabanas[c] is None]
            if not free_list:
                self.memory.session.notes.append("pool: no cabanas available that day")
                return []
            return [ItineraryItem(intent=intent, domain=self.domain, tool="reserve_cabana",
                args={"member_id": member_id, "cabana": free_list[0], "day": day},
                proposal=f"Reserve poolside cabana {free_list[0]}",
                choices={"cabana": [{"value": c, "label": f"Cabana {c}"} for c in free_list]})]
        if "lane" in req or "lap" in req:
            from ..mcp_servers.seed_data import STORE
            if STORE["aquatics"].get(day, {}).get("lap_lanes_open", 0) <= 0:
                self.memory.session.notes.append("pool: no lap lanes open that day")
                return []
            return [ItineraryItem(intent=intent, domain=self.domain, tool="reserve_lane",
                args={"member_id": member_id, "day": day},
                proposal="Reserve a lap lane")]
        guests = self.memory.registered_guests()[:3]
        elig = self._read("check_guest_pass_eligibility",
                          member_id=member_id, guest_count=len(guests))
        rules = ask_governing_docs("guest pass aquatics pool guest privileges")
        cite = rules["citations"][0]["doc_id"] if rules["citations"] else "club-7.1"
        self.memory.session.notes.append(
            f"pool: guests {'ELIGIBLE' if elig['eligible'] else 'NOT eligible'} "
            f"({elig['passes_remaining']} passes remaining) per [{cite}]")
        if not elig["eligible"]:
            return []
        return [ItineraryItem(
            intent=intent, domain=self.domain, tool="issue_guest_passes",
            args={"member_id": member_id, "guest_names": guests, "day": self._target_day()},
            proposal=(f"Pool guest passes for {', '.join(guests)} "
                      f"(uses 3 of {elig['passes_remaining']} remaining, [{cite}])"),
        )]


class MarinaAgent(DomainHandler):
    name, domain = "marina-agent", "marina"

    def _handle(self, intent: str) -> list[ItineraryItem]:
        member_id = self.memory.member_id
        req = (self.memory.session.raw_request or intent).lower()
        day = self._target_day()
        if "fuel" in req:
            self.memory.session.notes.append(
                "marina: fuel is authorized and billed at the fuel dock — the charge "
                "needs your explicit approval on site")
            return []
        info = self._read("list_launch_windows", member_id=member_id, day=day)
        if not info["windows"]:
            self.memory.session.notes.append("marina: no launch windows")
            return []
        sunset = info["windows"][-1]  # latest window ~ sunset
        passengers = [self.memory.profile["name"]] + self.memory.registered_guests()[:3]
        return [ItineraryItem(
            intent=intent, domain=self.domain, tool="schedule_launch",
            args={"member_id": member_id, "day": day, "time": sunset,
                  "passengers": passengers},
            proposal=(f"Sunset launch at {sunset}, {len(passengers)} aboard "
                      f"({info['slip_note']})"),
            choices={"time": [{"value": w, "label": w} for w in info["windows"]]},
        )]


# Exterior-modification cues that require an ARC request (vs. a plain rules question).
_MOD_WORDS = ("paint", "repaint", "door", "color", "colour", "fence", "shed", "awning",
              "sign", "exterior", "install", "build", "landscap", "deck", "patio",
              "antenna", "satellite", "solar", "window")
_PALETTE_COLORS = ("classic navy", "estate white", "forest green", "charleston black",
                   "navy", "white", "green", "black")


def _extract_color(text: str) -> str | None:
    for c in _PALETTE_COLORS + ("blue", "red", "grey", "gray", "yellow", "brown"):
        if c in text:
            return c
    return None


def _mod_label(text: str) -> str:
    for key, label in (("fence", "fence installation"), ("shed", "shed installation"),
                       ("sign", "signage"), ("awning", "awning installation"),
                       ("solar", "solar panel installation"), ("deck", "deck addition"),
                       ("patio", "patio addition"), ("landscap", "landscaping change"),
                       ("window", "window replacement"), ("antenna", "antenna/satellite install"),
                       ("satellite", "antenna/satellite install")):
        if key in text:
            return label
    return "exterior modification"


class HoaAgent(DomainHandler):
    name, domain = "hoa-agent", "hoa"

    def _handle(self, intent: str) -> list[ItineraryItem]:
        member_id = self.memory.member_id
        request = (self.memory.session.raw_request or intent).strip()

        # Ground the answer in whatever the member actually asked — not a fixed query.
        from ..mcp_servers.seed_data import GOVERNING_DOCS
        rules = ask_governing_docs(request or "exterior modification approval")
        if rules["citations"]:
            top = rules["citations"][0]
        else:  # no lexical hit -> fall back to the exterior-modifications rule, with its text
            d = next(x for x in GOVERNING_DOCS if x["doc_id"] == "ccr-4.2")
            top = {"doc_id": "ccr-4.2", "title": d["title"], "snippet": d["text"][:180]}
        doc_id, title, snippet = top["doc_id"], top["title"], top.get("snippet", "")

        # Cited answer grounded in the retrieved governing document.
        self.memory.session.notes.append(
            f"hoa: per [{doc_id}] {title} — {snippet[:180].rstrip()}")

        lower = request.lower()
        if not any(w in lower for w in _MOD_WORDS):
            # A general governance question: a cited answer is the whole response,
            # no Architectural Review request is created.
            return []

        # It's an exterior change -> draft (never submit) an ARC request that
        # reflects the actual modification, checking the pre-approved palette.
        full = next((d["text"] for d in GOVERNING_DOCS if d["doc_id"] == doc_id), "")
        color = _extract_color(lower)
        if color and "door" in lower:
            on_palette = color in full.lower()
            modification = f"front door repaint ({color.title()})"
            self.memory.session.notes.append(
                f"hoa: {color.title()} front door is "
                f"{'on the pre-approved palette (expedited ~5 business days)' if on_palette else 'not on the pre-approved palette (standard review)'} "
                f"per [{doc_id}]; ARC approval still required")
            details = (f"Repaint front door {color.title()}; "
                       + ("pre-approved palette color, expedited review requested."
                          if on_palette else "standard ARC review required."))
        else:
            modification = _mod_label(lower)
            details = (f"Member request: {request}. Per [{doc_id}] {title}, ARC "
                       f"approval is required for exterior changes.")

        return [ItineraryItem(
            intent=intent, domain=self.domain, tool="draft_arc_request",
            args={"member_id": member_id, "modification": modification, "details": details},
            proposal=(f"Draft ARC request — {modification} (grounded in [{doc_id}]; "
                      f"draft only, member reviews and submits)"),
        )]


HANDLERS: dict[str, type[DomainHandler]] = {
    "golf": GolfAgent, "dining": DiningAgent, "tennis": TennisAgent,
    "pool": PoolAgent, "marina": MarinaAgent, "hoa": HoaAgent,
}
