"""Local browser UI for the Viba Club concierge.

Zero external dependencies (stdlib http.server only) and no API key: it drives
the SAME ConciergeOrchestrator used by the CLI demo and tests, so what you see
in the browser is the real propose -> gate -> confirm/decline -> commit flow
with the live guardrail audit trail.

    python3 scripts/webapp.py            # serve at http://localhost:8000
    python3 scripts/webapp.py --port 9000

Nothing books or charges until you click Confirm; Decline leaves zero side
effects. Each new "Plan" resets the mock systems of record to a clean seed.
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
import webbrowser
from dataclasses import asdict
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Make the package importable no matter where this script is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from viba_concierge.core.orchestrator import ConciergeOrchestrator
from viba_concierge.core.policy import (
    GuardrailViolation, PolicyEngine, Verdict, guarded_call,
)
from viba_concierge.mcp_servers.connectors import TOOL_REGISTRY, is_side_effect
from viba_concierge.mcp_servers.seed_data import SATURDAY, STORE, SUNDAY, TIER_BENEFITS, reset_store

def _load_dotenv() -> None:
    """Minimal .env loader (no dependency) so GOOGLE_API_KEY is picked up."""
    import os
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


MEMBER_ID = "M-1014"  # default demo member

# Who is signed in this (single-user, local) session, set via /api/login.
SESSION = {"member_id": MEMBER_ID, "role": "member"}


def _mid() -> str:
    return SESSION["member_id"]


# Members offered on the login screen / staff acting-for (staff is a separate role).
# Built from the seeded roster so the two never drift.
LOGIN_MEMBERS = [
    {"id": mid, "name": rec["name"], "tier": rec["tier"], "standing": rec["standing"]}
    for mid, rec in STORE["members"].items()
]
DEFAULT_REQUEST = (
    "Plan Saturday for me and three guests - morning golf, lunch at the Grill, "
    "afternoon tennis, sunset on the boat. Can my guests use the pool? Also, "
    "I'd like to repaint my front door navy - am I allowed?"
)

# Server-side session state: trace_id -> (orchestrator, ConciergeResult).
# A local single-member demo, so a plain dict is enough.
_SESSIONS: dict[str, tuple] = {}


def _member_name() -> str:
    return STORE["members"].get(_mid(), {}).get("name", _mid())


def _result_payload(result, orch=None) -> dict:
    # Structured audit rows (verdict / tool / reason) for a clean table render,
    # taken from the policy engine's immutable entries when available.
    audit_rows = []
    if orch is not None:
        audit_rows = [{"verdict": e["verdict"], "tool": e["tool"], "reason": e["reason"],
                       "override": e.get("override", False)}
                      for e in orch.policy.audit.entries]
    return {
        "trace_id": result.trace_id,
        "member": _member_name(),
        "itinerary": [asdict(item) for item in result.itinerary],
        "notes": result.notes,
        "audit": result.audit,        # legacy pre-formatted strings (fallback)
        "audit_rows": audit_rows,
        "committed": [asdict(item) for item in result.committed],
        "blocked": result.blocked,
    }


def do_propose(request_text: str) -> dict:
    reset_store()  # fresh systems of record for every new plan
    orch = ConciergeOrchestrator(_mid())
    result = orch.propose(request_text or DEFAULT_REQUEST)
    _SESSIONS[result.trace_id] = (orch, result)
    return _result_payload(result, orch)


def do_commit(trace_id: str, approved: bool, edits: list | None = None) -> dict:
    session = _SESSIONS.get(trace_id)
    if session is None:
        return {"error": "unknown or expired trace_id; click Plan again"}
    orch, result = session
    # Apply the member's inline picks (day/clinic/cabana/time) before committing.
    if approved and edits:
        for e in edits:
            i = e.get("index")
            if isinstance(i, int) and 0 <= i < len(result.itinerary):
                result.itinerary[i].args.update(e.get("args", {}))
    committed = orch.commit(result, approved=approved)
    return _result_payload(committed, orch)


# --------------------------- a la carte actions ----------------------------
# Single-tool actions with member-supplied inputs, run through the SAME
# guardrail layer: reads execute immediately; side-effects return
# needs_confirmation until the member confirms (charge tools every time).
_ACTION_POLICY = PolicyEngine()


def _augment(tool_name: str, args: dict) -> dict:
    """Fill server-known args (member, day, passenger/guest lists) so the client
    only supplies the choices the member actually makes."""
    params = inspect.signature(TOOL_REGISTRY[tool_name]["fn"]).parameters
    m = STORE["members"].get(_mid(), {})
    guests = list(m.get("registered_guests", []))
    if "member_id" in params:
        args.setdefault("member_id", _mid())
    if "day" in params:
        args.setdefault("day", SATURDAY)
    if "passengers" in params:
        args.setdefault("passengers", [m.get("name", "")] + guests[:3])
    if "guest_names" in params:
        cap = m.get("entitlements", {}).get("guests_per_visit_max", len(guests))
        args.setdefault("guest_names", guests[:cap])
    return args


def do_action(tool_name: str, args: dict, confirmed: bool, override: bool = False) -> dict:
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"unknown tool '{tool_name}'"}
    # Only staff may waive the standing gate.
    allow_override = bool(override) and SESSION["role"] == "staff"
    # Reads (e.g. get_menu) carry no member_id, so the policy engine can't gate
    # them by standing. Lock the whole panel for a suspended account instead.
    member = STORE["members"].get(_mid(), {})
    if member.get("standing") != "good" and not allow_override:
        params = inspect.signature(TOOL_REGISTRY[tool_name]["fn"]).parameters
        if "member_id" not in params:
            return {"denied": True, "verdict": "deny",
                    "reason": f"account suspended — {member.get('standing')} (CC&R 9.1)"}
    call_args = _augment(tool_name, dict(args or {}))
    if confirmed:
        _ACTION_POLICY.confirm(tool_name)
    _ACTION_POLICY.staff_override = allow_override
    actor = "staff" if SESSION["role"] == "staff" else "web-action"
    try:
        result = guarded_call(_ACTION_POLICY, actor, tool_name, **call_args)
        # Re-lock side-effect tools so each run re-confirms (shows the gate every time).
        if is_side_effect(tool_name):
            _ACTION_POLICY._confirmed.discard(tool_name)
        return {"ok": True, "result": result, "audit": _ACTION_POLICY.audit.summary()[-1],
                "override": _ACTION_POLICY.audit.entries[-1].get("override", False)}
    except GuardrailViolation as violation:
        v = violation.decision.verdict
        return {
            "needs_confirmation": v is Verdict.NEEDS_CONFIRMATION,
            "denied": v is Verdict.DENY,
            "verdict": v.value,
            "reason": violation.decision.reason,
            "audit": _ACTION_POLICY.audit.summary()[-1],
        }
    except Exception as err:  # connector business-rule rejection (e.g. cabana taken)
        return {"error": f"{type(err).__name__}: {err}"}
    finally:
        _ACTION_POLICY.staff_override = False


def do_reset() -> dict:
    global _ACTION_POLICY
    reset_store()
    _SESSIONS.clear()
    _ACTION_POLICY = PolicyEngine()
    return {"ok": True}


# ---------------------- state snapshot (portal + dashboard) ----------------
ANNUAL_PASSES = 6  # seeded starting allotment, for the "x of 6" display


def do_state() -> dict:
    """One read-only snapshot of every system of record, for the staff portal,
    member dashboard, and live status strip."""
    day = SATURDAY
    mid = _mid()
    m = STORE["members"][mid]
    ent = m["entitlements"]

    # The member's actual bookable days (next week): all weekdays, plus the
    # weekend days their tier includes.
    member_wk = [d.lower() for d in TIER_BENEFITS[m["tier"]]["weekend_days"]]
    bookable_days = []
    for i in range(1, 8):
        dd = date.today() + timedelta(days=i)
        if dd.weekday() < 5 or dd.strftime("%A").lower() in member_wk:
            bookable_days.append({"date": dd.isoformat(),
                                  "label": f"{dd.strftime('%A')} · {dd.isoformat()}"})

    tee = [{"time": t, "booked_by": v["booked_by"], "slots": v["slots"]}
           for t, v in sorted(STORE["golf_teesheet"].get(day, {}).items())]
    courts = [{"court": ct, "time": hr, "holder": holder}
              for ct, hours in STORE["racquet_courts"].get(day, {}).items()
              for hr, holder in sorted(hours.items())]
    clinics = [{"name": c["name"], "time": c["time"],
                "spots_open": c["spots_open"], "roster": c["roster"]}
               for c in STORE["clinics"].get(day, [])]
    aq = STORE["aquatics"].get(day, {})
    cabanas = [{"id": k, "holder": v} for k, v in aq.get("cabanas", {}).items()]
    lanes_open = aq.get("lap_lanes_open", 0)
    venues = {venue: [{"time": t, "covers_open": n}
                      for t, n in sorted(days.get(day, {}).items())]
              for venue, days in STORE["dining"]["venues"].items()}
    folio = STORE["dining"]["folio_charges"]
    fuel = STORE["marina"]["fuel_charges"]
    folio_total = round(sum(c["amount"] for c in folio)
                        + sum(c["amount"] for c in fuel), 2)

    # This member's holdings, merged from the systems of record + booking history.
    mine = []
    for t in tee:
        if t["booked_by"] == mid:
            mine.append({"domain": "golf", "detail": f"Golf tee time {t['time']}"})
    for c in courts:
        if c["holder"] == mid:
            mine.append({"domain": "tennis", "detail": f"Court {c['court']} at {c['time']}"})
    for cl in clinics:
        if mid in cl["roster"]:
            mine.append({"domain": "tennis", "detail": f"Clinic: {cl['name']} at {cl['time']}"})
    for cb in cabanas:
        if cb["holder"] == mid:
            mine.append({"domain": "pool", "detail": f"Cabana {cb['id']}"})
    for h in m.get("history", []):
        r = h.get("result") or {}
        if h.get("type") == "reserve_table":
            mine.append({"domain": "dining", "detail": f"Table at {r.get('venue')} {r.get('time')}"})
        elif h.get("type") == "schedule_launch":
            mine.append({"domain": "marina", "detail": f"Sunset launch {r.get('time')}"})
        elif h.get("type") == "issue_guest_passes":
            mine.append({"domain": "pool", "detail": f"Guest passes: {', '.join(r.get('guests', []))}"})

    return {
        "day": day,
        "member": {
            "name": m["name"], "tier": m["tier"], "standing": m["standing"],
            "residence": m["residence"],
            "passes_remaining": ent["guest_passes_remaining"],
            "passes_max": TIER_BENEFITS[m["tier"]]["annual_passes"],
            "guests_per_visit_max": ent["guests_per_visit_max"],
            "registered_guests": m["registered_guests"],
            "preferences": m["preferences"],
            "dues": STORE["hoa"]["dues"].get(mid, {}),
            "bookings": mine,
            "bookable_days": bookable_days,
            "tier_benefits": {
                "facilities": list(TIER_BENEFITS[m["tier"]]["facilities"]),
                "annual_passes": TIER_BENEFITS[m["tier"]]["annual_passes"],
                "guests_per_visit_max": TIER_BENEFITS[m["tier"]]["guests_per_visit_max"],
                "weekend_days": list(TIER_BENEFITS[m["tier"]]["weekend_days"]),
            },
        },
        "golf": tee, "courts": courts, "clinics": clinics,
        "cabanas": cabanas, "lanes_open": lanes_open,
        "launch_windows": STORE["marina"]["launch_windows"].get(day, []),
        "fuel_charges": fuel, "dining": venues, "folio": folio, "folio_total": folio_total,
        "arc_requests": STORE["hoa"]["arc_requests"],
        "member_id": mid,
        "role": SESSION["role"],
        "names": {mi: rec["name"] for mi, rec in STORE["members"].items()},
        "weekend_dates": {"Saturday": SATURDAY, "Sunday": SUNDAY},
        "today": date.today().strftime("%A · %b %-d"),
    }


def do_login(member_id: str, role: str) -> dict:
    if role == "staff":
        SESSION["role"] = "staff"
        # Staff act on behalf of a member; default to the first member.
        SESSION["member_id"] = member_id if member_id in STORE["members"] else "M-1014"
    else:
        if member_id not in STORE["members"]:
            return {"error": f"unknown member '{member_id}'"}
        SESSION["role"] = "member"
        SESSION["member_id"] = member_id
    return do_whoami()


def do_act_as(member_id: str) -> dict:
    """Staff selects which member to plan/book for."""
    if SESSION["role"] != "staff":
        return {"error": "only staff can act on behalf of a member"}
    if member_id not in STORE["members"]:
        return {"error": f"unknown member '{member_id}'"}
    SESSION["member_id"] = member_id
    return do_whoami()


def do_whoami() -> dict:
    return {
        "role": SESSION["role"],
        "member_id": SESSION["member_id"],
        "name": STORE["members"].get(SESSION["member_id"], {}).get("name", "?"),
        "members": LOGIN_MEMBERS,
    }


# ------------------------------- live mode ---------------------------------
def _live():
    """Lazy import so dry-run never depends on google-adk being installed."""
    from viba_concierge.agents import live
    return live


def _session_member() -> dict:
    m = STORE["members"].get(_mid(), {})
    return {"id": _mid(), "name": m.get("name", "Member"),
            "tier": m.get("tier", ""), "standing": m.get("standing", "good")}


def do_live_propose(request: str) -> dict:
    try:
        return _live().live_propose(request or DEFAULT_REQUEST, _session_member())
    except Exception as err:
        return {"error": f"{type(err).__name__}: {err}"}


def do_live_confirm(session_id: str, approved: bool) -> dict:
    try:
        return _live().live_confirm(session_id, approved, _session_member())
    except Exception as err:
        return {"error": f"{type(err).__name__}: {err}"}


def live_available() -> dict:
    import os
    try:
        import google.adk  # noqa: F401
        adk = True
    except Exception:
        adk = False
    return {"adk_installed": adk, "key_set": bool(os.getenv("GOOGLE_API_KEY"))}


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Viba Club Concierge</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;1,500&family=Hanken+Grotesk:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root { --green:#1F3A30; --green2:#2C5142; --sage:#9DB0A2;
          --cream:#FBF7EF; --parch:#EFE7D6; --parch2:#F3EDE1; --card:#F7F2E8;
          --line:#E2D8C5; --line2:#DACBAE; --gold:#A07C3E; --gold2:#C9A86A;
          --ink:#2A2520; --muted:#8A8071; --muted2:#5F5648; --bad:#9A463C; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--cream); color:var(--ink);
         font:16px/1.55 'Hanken Grotesk',sans-serif; -webkit-font-smoothing:antialiased; }
  .wrap { max-width:1200px; margin:0 auto; padding:40px 40px 72px; }
  /* Keep long-form reading content comfortably narrow even in the wide shell. */
  .sub, .how, .demonote, .modebar, .member, .whoami { max-width:900px; }
  .brand { display:flex; align-items:center; gap:12px; }
  .crest { width:40px; height:40px; border-radius:50%; background:var(--green);
           color:var(--parch2); display:grid; place-items:center;
           font:600 22px/1 'Cormorant Garamond',serif; border:1.5px solid var(--gold); }
  h1 { font:600 30px/1.05 'Cormorant Garamond',serif; margin:0; color:var(--green);
       letter-spacing:.01em; }
  .kicker { font-size:11px; letter-spacing:.22em; text-transform:uppercase;
            color:var(--gold); margin:0 0 2px; }
  .sub { color:var(--muted2); margin:14px 0 26px; font-size:15px;
         border-bottom:1px solid var(--line); padding-bottom:22px; }
  .overlay { position:fixed; inset:0; background:rgba(31,58,48,.55); backdrop-filter:blur(3px);
             display:grid; place-items:center; z-index:50; }
  .overlay.hidden { display:none; }
  .loginbox { background:var(--cream); border:1px solid var(--line); border-radius:10px;
              padding:30px 32px; width:min(400px,90vw); box-shadow:0 20px 60px rgba(0,0,0,.28); }
  .lh { font:600 32px 'Cormorant Garamond',serif; color:var(--green); margin:2px 0 20px; }
  .lopts { display:flex; flex-direction:column; gap:10px; margin-bottom:20px; }
  .lopt { display:flex; align-items:center; gap:12px; padding:12px 14px; border:1px solid var(--line2);
          border-radius:6px; cursor:pointer; background:var(--parch2); }
  .lopt:hover { border-color:var(--gold2); }
  .lopt.sel { border-color:var(--green); background:#EAF0EB; }
  .lopt .mono { width:36px; height:36px; }
  .lopt .crest { width:36px; height:36px; font-size:18px; }
  .lopt .ln { font:600 17px 'Cormorant Garamond',serif; color:var(--ink); }
  .lopt .lmeta { font-size:12px; color:var(--muted); }
  .lopt .lmeta .bad { color:var(--bad); font-weight:600; }
  .loginbox button { width:100%; padding:13px; font-size:15px; }
  .whoami { font-size:12px; color:var(--muted2); margin:8px 0 0; }
  .whoami a { color:var(--gold); cursor:pointer; text-decoration:underline; }
  .strip { display:flex; gap:0; flex-wrap:wrap; align-items:center; background:var(--green);
           color:var(--parch2); border-radius:6px; padding:11px 18px; margin:0 0 18px; }
  .strip .empty { color:var(--parch2); font-style:italic; opacity:.7; }
  .sitem { display:flex; flex-direction:column; padding:0 18px; border-right:1px solid rgba(255,255,255,.14); }
  .sitem:first-child { padding-left:0; } .sitem:last-child { border-right:0; }
  .sk { color:var(--gold2); text-transform:uppercase; letter-spacing:.1em; font-size:9px; }
  .sv { font:600 16px/1.2 'Cormorant Garamond',serif; }
  .sv.warn { color:#F0B4A6; }
  .tabs { display:flex; gap:2px; border-bottom:1px solid var(--line); margin:0 0 24px; }
  .tab { background:transparent; color:var(--muted2); border:0; border-bottom:2px solid transparent;
         border-radius:0; padding:11px 18px; font:600 14px 'Hanken Grotesk',sans-serif;
         letter-spacing:.02em; }
  .tab:hover { color:var(--green); background:transparent; }
  .tab.on { color:var(--green); border-bottom-color:var(--gold); }
  .actingbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; background:var(--parch2);
               border:1px solid var(--gold2); border-radius:6px; padding:9px 14px; margin:0 0 22px; font-size:13px; }
  .ablabel { text-transform:uppercase; letter-spacing:.12em; font-size:10px; color:var(--gold); font-weight:600; }
  .actingbar select { background:var(--cream); border:1px solid var(--line2); border-radius:5px;
                      padding:6px 10px; font:14px 'Hanken Grotesk',sans-serif; color:var(--ink); }
  .abnote { color:var(--muted); }
  .grid2 { display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:20px; }
  .grid2 .card { margin-top:0; }
  @media (max-width:640px){ .grid2 { grid-template-columns:1fr; } .sitem { padding:4px 12px 4px 0; } }
  .mchead { display:flex; align-items:center; gap:14px; }
  .mono.lg { width:50px; height:50px; font-size:20px; }
  .mchead h3 { margin:0; font:600 23px 'Cormorant Garamond',serif; color:var(--green); }
  .mc-sub { color:var(--muted); font-size:13px; }
  .sbadge { margin-left:auto; padding:4px 12px; border-radius:20px; font-size:10px;
            text-transform:uppercase; letter-spacing:.1em; border:1px solid; font-weight:600; }
  .sbadge.good { color:var(--green); border-color:var(--sage); background:#EAF0EB; }
  .sbadge.bad { color:var(--bad); border-color:var(--bad); background:#F3E7E4; }
  .trow { display:flex; align-items:center; gap:10px; padding:8px 0;
          border-bottom:1px solid var(--line); font-size:14px; }
  .trow:last-child { border-bottom:0; }
  .trow .k { color:var(--muted2); text-transform:capitalize; }
  .trow .v { margin-left:auto; font-family:'IBM Plex Mono',monospace; font-size:13px; color:var(--ink); }
  .slot { display:flex; align-items:center; gap:10px; padding:7px 0;
          border-bottom:1px solid var(--line); font-size:14px; color:var(--muted2); }
  .slot:last-child { border-bottom:0; }
  .slot .t { font-family:'IBM Plex Mono',monospace; color:var(--green2); flex:0 0 50px; }
  .slot .who { margin-left:auto; font-size:12px; }
  .free { color:var(--muted); } .mineflag { color:var(--green); font-weight:600; }
  .vhead { font:600 15px 'Cormorant Garamond',serif; color:var(--green); margin:10px 0 2px; }
  .empty { color:var(--muted); font-style:italic; font-size:14px; }
  .how { display:flex; gap:12px; margin:0 0 26px; flex-wrap:wrap; }
  .hstep { flex:1; min-width:150px; background:var(--card); border:1px solid var(--line);
           border-radius:6px; padding:13px 15px; font-size:13px; color:var(--muted2);
           line-height:1.4; }
  .hstep b { display:block; color:var(--green); font:600 17px 'Cormorant Garamond',serif;
             margin:2px 0 3px; }
  .hn { display:inline-grid; place-items:center; width:22px; height:22px; border-radius:50%;
        background:var(--green); color:var(--parch2); font-size:11px; font-weight:600;
        float:right; }
  .demonote { font-size:13px; color:var(--muted2); background:var(--parch2);
              border:1px dashed var(--line2); border-radius:6px; padding:9px 13px;
              margin:0 0 22px; }
  .flabel { display:block; font:600 19px 'Cormorant Garamond',serif; color:var(--green);
            margin:0 0 9px; }
  .examples { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:11px; }
  .exlabel { font-size:11px; color:var(--muted); text-transform:uppercase;
             letter-spacing:.14em; }
  .chip { background:var(--parch2); border:1px solid var(--line2); color:var(--green2);
          border-radius:20px; padding:7px 13px; font-size:13px; letter-spacing:0; }
  .chip:hover { background:var(--parch); border-color:var(--gold2); }
  .member { display:flex; align-items:center; gap:12px; margin:0 0 10px; }
  .mono { width:34px; height:34px; border-radius:50%; background:var(--green2);
          color:var(--parch2); display:grid; place-items:center;
          font:600 14px/1 'Hanken Grotesk',sans-serif; }
  .member b { font-weight:600; } .member small { color:var(--gold);
          letter-spacing:.12em; text-transform:uppercase; font-size:11px; }
  textarea { width:100%; min-height:104px; background:var(--parch2); color:var(--ink);
             border:1px solid var(--line2); border-radius:6px; padding:14px 16px;
             font:16px/1.5 'Cormorant Garamond',serif; resize:vertical; }
  textarea:focus { outline:none; border-color:var(--gold2); }
  .row { display:flex; gap:12px; margin-top:14px; flex-wrap:wrap; }
  button { border:0; border-radius:5px; padding:12px 22px; font:600 14px/1 'Hanken Grotesk',sans-serif;
           letter-spacing:.03em; cursor:pointer; color:var(--parch2); background:var(--green);
           transition:background .15s; }
  button:hover { background:var(--green2); }
  button.ghost { background:transparent; color:var(--muted2); border:1px solid var(--line2); }
  button.ghost:hover { background:var(--parch); }
  button.ok  { background:var(--green); } button.ok:hover { background:var(--green2); }
  button.bad { background:transparent; color:var(--bad); border:1px solid var(--bad); }
  button.bad:hover { background:#F0E6E2; }
  button:disabled { opacity:.45; cursor:not-allowed; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:6px;
          padding:20px 22px; margin-top:20px; }
  .card h2 { font-size:11px; text-transform:uppercase; letter-spacing:.2em;
             color:var(--gold); margin:0 0 14px; font-weight:600; }
  .item { display:flex; align-items:flex-start; gap:13px; padding:12px 0;
          border-bottom:1px solid var(--line); }
  .item:last-child { border-bottom:0; }
  .tag { flex:0 0 30px; width:30px; height:30px; border-radius:50%;
         background:var(--parch); color:var(--green); display:grid; place-items:center;
         font:600 15px/1 'Cormorant Garamond',serif; border:1px solid var(--line2); }
  .item .body { flex:1; }
  .item .dom { font-size:10px; letter-spacing:.16em; text-transform:uppercase;
               color:var(--gold); }
  .item .prop { font:500 17px/1.35 'Cormorant Garamond',serif; color:var(--ink); }
  .status { margin-left:auto; font-size:10px; letter-spacing:.12em; text-transform:uppercase;
            padding:4px 11px; border-radius:20px; border:1px solid var(--line2);
            color:var(--muted); align-self:center; white-space:nowrap; }
  .status.committed { color:var(--green); border-color:var(--sage); background:#EAF0EB; }
  .status.proposed  { color:var(--gold); border-color:var(--gold2); }
  .status.declined  { color:var(--muted); }
  .status.failed    { color:var(--bad); border-color:var(--bad); }
  .gate { display:flex; align-items:center; gap:12px; background:var(--green);
          color:var(--parch2); border-radius:6px; padding:15px 18px; margin-top:20px;
          font-size:14px; border-left:4px solid var(--gold2); }
  ul.notes { margin:0; padding-left:20px; color:var(--muted2); }
  ul.notes li { margin:7px 0; font-size:15px; }
  .audit { display:flex; flex-direction:column; }
  .arow { display:flex; align-items:center; gap:12px; padding:8px 0;
          border-bottom:1px solid var(--line); }
  .arow:last-child { border-bottom:0; }
  .badge { flex:0 0 auto; width:112px; text-align:center; font-size:10px;
           letter-spacing:.08em; text-transform:uppercase; padding:4px 0; border-radius:4px;
           border:1px solid; font-weight:600; }
  .b-allow { color:var(--green2); border-color:var(--sage); background:#EAF0EB; }
  .b-needs_confirmation { color:var(--gold); border-color:var(--gold2); background:#F6EFDD; }
  .b-deny { color:var(--bad); border-color:var(--bad); background:#F3E7E4; }
  .b-override { color:var(--gold); border-color:var(--gold); background:#F6EFDD; }
  .atool { font-family:'IBM Plex Mono',monospace; font-size:13px; color:var(--ink); }
  .areason { color:var(--muted); font-size:13px; font-style:italic; margin-left:auto;
             text-align:right; }
  .hidden { display:none; }
  .trace { color:var(--muted); font-size:11px; letter-spacing:.08em; margin-top:12px;
           font-family:'IBM Plex Mono',monospace; }
  .spin { color:var(--gold); font-size:15px; margin-top:18px;
          font-style:italic; font-family:'Cormorant Garamond',serif; }
  .modebar { display:flex; align-items:center; gap:8px; margin:0 0 16px; flex-wrap:wrap; }
  .mlabel { font-size:11px; letter-spacing:.16em; text-transform:uppercase;
            color:var(--gold); margin-right:2px; }
  .pill { background:transparent; color:var(--muted2); border:1px solid var(--line2);
          border-radius:20px; padding:7px 15px; font-size:13px; }
  .pill:hover { background:var(--parch); }
  .pill.on { background:var(--green); color:var(--parch2); border-color:var(--green); }
  .pill:disabled { opacity:.4; cursor:not-allowed; }
  .mnote { font-size:12px; color:var(--muted); margin-left:4px; font-style:italic; }
  .step { padding:9px 0 9px 15px; border-left:2px solid var(--line2); margin-left:4px; }
  .step .who { font-size:10px; letter-spacing:.14em; text-transform:uppercase;
               color:var(--gold); margin-bottom:2px; }
  .step.tool { border-left-color:var(--green2); }
  .step.tool code { font-family:'IBM Plex Mono',monospace; font-size:13px;
                    color:var(--green2); word-break:break-word; }
  .step.gate { border-left-color:var(--gold2); color:var(--muted2); }
  .step.result { border-left-color:var(--sage); font-size:14px; color:var(--muted2); }
  .step .txt { font:500 16px/1.45 'Cormorant Garamond',serif; color:var(--ink); }
  .acaption { color:var(--muted2); font-size:14px; margin:-6px 0 16px; }
  .suspend { background:#F3E7E4; border:1px solid var(--bad); color:var(--bad);
             border-radius:6px; padding:11px 14px; font-size:13px; margin:0 0 16px; }
  .act.disabled { opacity:.45; }
  .suspend .ovr { display:inline-flex; align-items:center; gap:6px; margin-left:4px;
                  color:var(--green); font-weight:600; cursor:pointer; }
  .act { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:12px 0;
         border-bottom:1px solid var(--line); }
  .act:last-child { border-bottom:0; }
  .act .alabel { flex:0 0 180px; font:500 16px/1.3 'Cormorant Garamond',serif; }
  .act .chg { color:var(--gold); font-size:10px; letter-spacing:.12em; display:block;
              text-transform:uppercase; font-family:'Hanken Grotesk',sans-serif; }
  .act select, .act input { background:var(--parch2); color:var(--ink);
         border:1px solid var(--line2); border-radius:5px; padding:8px 10px;
         font:14px 'Hanken Grotesk',sans-serif; }
  .act input { width:90px; }
  .act button { padding:9px 16px; font-size:13px; }
  .act .out { flex-basis:100%; font-size:14px; margin-top:4px; min-height:1px; }
  .act .out .ok  { color:var(--green2); }
  .act .out .err { color:var(--bad); }
  .act .confirm { flex-basis:100%; display:flex; align-items:center; gap:10px;
                  flex-wrap:wrap; background:var(--parch2); border:1px solid var(--gold2);
                  border-radius:5px; padding:10px 12px; margin-top:6px; font-size:14px; }
  .act .confirm .why { color:var(--muted2); flex:1; min-width:200px; }
  .act .confirm button { padding:7px 14px; }
</style>
</head>
<body>
<div id="login" class="overlay">
  <div class="loginbox">
    <p class="kicker">Sign in to</p>
    <h2 class="lh">Viba Club</h2>
    <div class="lopts" id="lopts"></div>
    <button id="loginbtn" onclick="doLogin()">Enter</button>
  </div>
</div>

<div class="wrap">
  <p class="kicker">Concierge Track · Capstone</p>
  <div class="brand">
    <div class="crest">V</div>
    <h1>Viba Club&nbsp;·&nbsp;Member Concierge</h1>
  </div>
  <p class="whoami" id="whoami"></p>
  <p class="sub">A luxury club is scattered across six systems — a golf tee sheet, a
     dining POS, a tennis grid, a marina ledger, the pool registry and the HOA portal,
     each with its own rules. Instead of six forms, just say what you want in plain
     language. The concierge plans across all six, hands you <b>one itinerary</b>, and
     <b>never books or charges until you confirm</b>.</p>

  <div class="strip" id="strip"><span class="empty">loading club status…</span></div>

  <nav class="tabs">
    <button class="tab on" id="tab-b-concierge" onclick="switchTab('concierge')">Concierge</button>
    <button class="tab" id="tab-b-myclub" onclick="switchTab('myclub')">My Club</button>
    <button class="tab" id="tab-b-staff" onclick="switchTab('staff')">Staff Portal</button>
  </nav>

  <div id="actingbar" class="actingbar hidden">
    <span class="ablabel">Acting for</span>
    <select id="actingsel" onchange="actAs()"></select>
    <span class="abnote">— plan &amp; book on this member's behalf; charges post to their account</span>
  </div>

  <section id="tab-concierge" class="tabpanel">
  <div class="how">
    <div class="hstep"><span class="hn">1</span><b>Ask</b>
      Type a request below, or tap an example.</div>
    <div class="hstep"><span class="hn">2</span><b>Review</b>
      See one proposed plan — nothing is booked yet.</div>
    <div class="hstep"><span class="hn">3</span><b>Confirm</b>
      Approve to book, or decline for zero side effects.</div>
  </div>

  <div class="member">
    <div class="mono" id="cc-mono">ER</div>
    <div><b id="cc-name">Eleanor R.</b> &nbsp;<small id="cc-res">Member · Villa 14</small></div>
  </div>
  <p class="demonote" id="cc-demonote">You're exploring as a seeded demo member — every
     club system below is mock data, so book freely.</p>

  <div class="modebar">
    <span class="mlabel">Engine</span>
    <button class="pill on" id="m-dry" onclick="setMode('dry')">Dry-run · rules</button>
    <button class="pill" id="m-live" onclick="setMode('live')">Live · Gemini</button>
    <span class="mnote" id="mnote">checking…</span>
  </div>

  <label class="flabel" for="req" id="cc-flabel">What can I help you plan?</label>
  <textarea id="req"></textarea>
  <div class="examples">
    <span class="exlabel">Try</span>
    <button class="chip" onclick="setReq(0)">Plan my whole Saturday</button>
    <button class="chip" onclick="setReq(1)">Lunch at the Grill for 4</button>
    <button class="chip" onclick="setReq(2)">Golf for 4 Saturday morning</button>
    <button class="chip" onclick="setReq(3)">Can I repaint my door navy?</button>
  </div>
  <div class="row">
    <button id="plan" onclick="plan()">Plan it</button>
    <button class="ghost" onclick="resetAll()">Reset</button>
  </div>

  <div id="spin" class="spin hidden">Planning…</div>

  <div id="proposed" class="card hidden">
    <h2 id="prop-head">Proposed itinerary</h2>
    <div id="items"></div>
    <p class="trace" id="trace"></p>
  </div>

  <div id="gate" class="gate hidden">
    <span>⏸ Gate active — paused for your confirmation. Nothing booked, nothing charged.</span>
  </div>
  <div id="decide" class="row hidden">
    <button class="ok"  onclick="commit(true)">Confirm &amp; book</button>
    <button class="bad" onclick="commit(false)">Decline</button>
  </div>

  <div id="tracecard" class="card hidden">
    <h2>Agent reasoning · live (Gemini)</h2>
    <div id="tracelog"></div>
  </div>

  <div id="findings" class="card hidden">
    <h2>Findings</h2>
    <ul id="notes" class="notes"></ul>
  </div>

  <div id="auditcard" class="card hidden">
    <h2>Audit trail (PII redacted)</h2>
    <div id="audit" class="audit"></div>
  </div>

  <div class="card">
    <h2>À la carte · single actions</h2>
    <p class="acaption">Pick an action, set the details, and request it. Reads return
       at once; anything that books or charges pauses for your confirmation.</p>
    <div id="ac-suspend" class="suspend hidden"></div>
    <div id="actions"></div>
  </div>
  </section>

  <section id="tab-myclub" class="tabpanel hidden">
    <div class="card mchead">
      <div class="mono lg" id="mc-mono">ER</div>
      <div><h3 id="mc-name">Eleanor R.</h3><span id="mc-sub" class="mc-sub"></span></div>
      <span class="sbadge good" id="mc-standing">good</span>
    </div>
    <div id="mc-suspend" class="suspend hidden"></div>
    <div class="card">
      <h2>My reservations</h2>
      <div id="mc-bookings"></div>
    </div>
    <div class="grid2">
      <div class="card"><h2>Guest passes</h2><div id="mc-passes"></div></div>
      <div class="card"><h2>Folio &amp; dues</h2><div id="mc-folio"></div></div>
    </div>
    <div class="card"><h2>Preferences on file</h2><div id="mc-prefs"></div></div>
  </section>

  <section id="tab-staff" class="tabpanel hidden">
    <p class="demonote">Club operations — the other side of every member booking,
       live from the same systems of record. Book something in Concierge, then
       come back here.</p>
    <div class="grid2">
      <div class="card"><h2>Golf tee sheet</h2><div id="st-golf"></div></div>
      <div class="card"><h2>Courts &amp; clinics</h2><div id="st-tennis"></div></div>
      <div class="card"><h2>Aquatics</h2><div id="st-pool"></div></div>
      <div class="card"><h2>Marina</h2><div id="st-marina"></div></div>
      <div class="card"><h2>Dining &amp; folio</h2><div id="st-dining"></div></div>
      <div class="card"><h2>HOA · ARC queue</h2><div id="st-hoa"></div></div>
    </div>
  </section>
</div>

<script>
const DEFAULT_REQUEST = %DEFAULT_REQUEST%;
let TRACE = null;
document.getElementById('req').value = DEFAULT_REQUEST;

const EXAMPLES = [
  DEFAULT_REQUEST,
  "Reserve lunch at the Grill for 4 this Saturday.",
  "Book the earliest golf tee time for 4 players this Saturday morning.",
  "I'd like to repaint my front door navy — am I allowed?",
];
function setReq(i){ const r = document.getElementById('req'); r.value = EXAMPLES[i]; r.focus(); }

function el(id){ return document.getElementById(id); }
function show(id, on=true){ el(id).classList.toggle('hidden', !on); }

async function post(path, body){
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                              body: JSON.stringify(body)});
  return r.json();
}

const MONO = {golf:'G', dining:'D', tennis:'T', marina:'M', pool:'S', hoa:'H'};
function renderItems(items){
  const box = el('items'); box.innerHTML = '';
  items.forEach(it => {
    const row = document.createElement('div'); row.className = 'item';
    row.innerHTML = `<span class="tag">${MONO[it.domain] || it.domain[0].toUpperCase()}</span>
                     <span class="body"><span class="dom">${it.domain}</span>
                       <div class="prop">${it.proposal}</div></span>
                     <span class="status ${it.status}">${it.status}</span>`;
    box.appendChild(row);
  });
}

function renderAudit(rows){
  const box = el('audit'); box.innerHTML = '';
  (rows || []).forEach(r => {
    const row = document.createElement('div'); row.className = 'arow';
    const badge = r.override
      ? `<span class="badge b-override">override</span>`
      : `<span class="badge b-${r.verdict}">${r.verdict.replace(/_/g,' ')}</span>`;
    row.innerHTML = badge +
      `<code class="atool">${r.tool}</code><span class="areason">${r.reason}</span>`;
    box.appendChild(row);
  });
}

function paint(data, phase){
  renderItems(data.itinerary);
  el('trace').textContent = 'trace ' + data.trace_id + ' · member ' + data.member;
  show('proposed', true);
  el('prop-head').textContent = phase === 'committed'
    ? 'Itinerary — committed' : `Proposed itinerary (${data.itinerary.length} actions, none committed)`;
  show('findings', data.notes.length > 0);
  const notes = el('notes'); notes.innerHTML = '';
  data.notes.forEach(n => { const li=document.createElement('li'); li.textContent=n; notes.appendChild(li); });
  renderAudit(data.audit_rows); show('auditcard', (data.audit_rows || []).length > 0);
  const pending = phase === 'proposed';
  show('gate', pending); show('decide', pending);
}

let MODE = 'dry', LIVE_SID = null;
function setMode(m){
  if (el('m-' + m).disabled) return;
  MODE = m;
  el('m-dry').classList.toggle('on', m === 'dry');
  el('m-live').classList.toggle('on', m === 'live');
}

async function plan(){
  el('plan').disabled = true; show('spin', true);
  ['proposed','gate','decide','findings','auditcard','tracecard'].forEach(id=>show(id,false));
  if (MODE === 'live'){
    const data = await post('/api/live/propose', {request: el('req').value});
    show('spin', false); el('plan').disabled = false;
    if (data.error){ el('tracelog').innerHTML =
        `<div class="step gate">⚠ ${data.error}</div>`; show('tracecard', true); return; }
    LIVE_SID = data.session_id;
    renderTrace(data.trace, false);
    show('gate', true); show('decide', true);
    return;
  }
  const data = await post('/api/propose', {request: el('req').value});
  TRACE = data.trace_id;
  show('spin', false); el('plan').disabled = false;
  paint(data, 'proposed');
}

async function commit(approved){
  show('spin', true); show('gate', false); show('decide', false);
  if (MODE === 'live'){
    const data = await post('/api/live/confirm', {session_id: LIVE_SID, approved});
    show('spin', false);
    if (data.error){ alert(data.error); return; }
    renderTrace(data.trace, true);   // append the confirm turn
    loadState();
    return;
  }
  const data = await post('/api/commit', {trace_id: TRACE, approved});
  show('spin', false);
  if (data.error){ alert(data.error); return; }
  paint(data, approved ? 'committed' : 'declined');
  loadState();
}

function fmtArgs(a){
  return Object.entries(a || {}).map(([k,v]) => `${k}=${JSON.stringify(v)}`).join(', ');
}
function stepHTML(s){
  if (s.type === 'tool_call')
    return `<div class="step tool"><div class="who">${s.agent} → tool</div>
            <code>${s.tool}(${fmtArgs(s.args)})</code></div>`;
  if (s.type === 'gate')
    return `<div class="step gate"><div class="who">${s.agent} · gated</div>
            ⏸ ${(s.response && s.response.reason) || 'paused for confirmation'}</div>`;
  if (s.type === 'tool_result')
    return `<div class="step result"><div class="who">${s.agent} · ${s.tool}</div>
            ${typeof s.response === 'object' ? JSON.stringify(s.response) : s.response}</div>`;
  return `<div class="step"><div class="who">${s.agent}</div>
          <div class="txt">${s.text}</div></div>`;
}
function renderTrace(trace, append){
  const html = (trace || []).map(stepHTML).join('') || '<div class="step">no steps returned</div>';
  el('tracelog').innerHTML = append ? el('tracelog').innerHTML + html : html;
  show('tracecard', true);
}

async function initLive(){
  try {
    const s = await (await fetch('/api/live/status')).json();
    if (!s.adk_installed){ el('m-live').disabled = true; el('mnote').textContent = 'live needs google-adk'; }
    else if (!s.key_set){ el('mnote').textContent = 'live needs GOOGLE_API_KEY in .env'; }
    else { el('mnote').textContent = 'Gemini ready ✓'; }
  } catch(e){ el('mnote').textContent = ''; }
}
initLive();

// ---- à la carte single actions (the new MCP verbs, with inputs) ----
const ACTIONS = [
  {tool:'get_menu',        label:'View the Grill menu', read:true,
   inputs:[{name:'venue', kind:'select', opts:['The Grill']}]},
  {tool:'reserve_lane',    label:'Reserve a lap lane', inputs:[]},
  {tool:'reserve_cabana',  label:'Reserve a cabana',
   inputs:[{name:'cabana', kind:'select', opts:['C1','C2','C3']}]},
  {tool:'join_clinic',     label:'Join a clinic',
   inputs:[{name:'clinic_name', kind:'select', opts:['Cardio Tennis','Junior Pickleball']}]},
  {tool:'cancel_tee_time', label:'Cancel a tee time',
   inputs:[{name:'time', kind:'select', opts:['07:40','08:10','08:50']}]},
  {tool:'log_fuel',        label:'Log marina fuel', charge:true,
   inputs:[{name:'gallons', kind:'number', value:10}]},
];

function buildActions(){
  const box = el('actions'); box.innerHTML = '';
  ACTIONS.forEach((a, idx) => {
    const row = document.createElement('div'); row.className = 'act';
    let controls = '';
    a.inputs.forEach(inp => {
      if (inp.kind === 'select')
        controls += `<select data-k="${inp.name}">` +
          inp.opts.map(o=>`<option>${o}</option>`).join('') + `</select>`;
      else
        controls += `<input data-k="${inp.name}" type="number" min="1" value="${inp.value||1}">`;
    });
    row.innerHTML =
      `<span class="alabel">${a.label}${a.charge?'<span class="chg">charges folio</span>':''}</span>
       ${controls}
       <button onclick="runAction(${idx}, this)">Request</button>
       <div class="confirm" style="display:none"></div>
       <div class="out"></div>`;
    box.appendChild(row);
  });
}

function collectArgs(row, spec){
  const args = {};
  spec.inputs.forEach(inp => {
    const node = row.querySelector(`[data-k="${inp.name}"]`);
    args[inp.name] = inp.kind === 'number' ? Number(node.value) : node.value;
  });
  return args;
}

async function runAction(idx, btn, confirmed=false){
  const spec = ACTIONS[idx];
  const row = btn.closest('.act');
  const out = row.querySelector('.out');
  const confirmBox = row.querySelector('.confirm');
  out.innerHTML = ''; confirmBox.style.display = 'none';
  const data = await post('/api/action',
    {tool: spec.tool, args: collectArgs(row, spec), confirmed, override: OVERRIDE});

  if (data.needs_confirmation){
    confirmBox.style.display = 'flex';
    confirmBox.innerHTML =
      `<span class="why">⏸ ${data.reason}</span>
       <button class="ok"  onclick="confirmAction(${idx}, this)">Confirm</button>
       <button class="ghost" onclick="this.closest('.confirm').style.display='none'">Cancel</button>`;
    return;
  }
  if (data.denied){ out.innerHTML = `<span class="err">⊘ Denied — ${data.reason}</span>`; return; }
  if (data.error){ out.innerHTML = `<span class="err">✕ ${data.error}</span>`; return; }
  const ov = data.override ? `<span class="badge b-override">override</span> ` : '';
  out.innerHTML = `${ov}<span class="ok">✓ ${fmtResult(spec.tool, data.result)}</span>`;
  loadState();
}

function confirmAction(idx, btn){
  const row = btn.closest('.act');
  runAction(idx, row.querySelector('button'), true);
}

function fmtResult(tool, r){
  switch (tool){
    case 'get_menu':
      return 'Menu — ' + r.map(m=>`${m.item} $${m.price}`).join(' · ');
    case 'log_fuel':
      return `Charged $${r.amount} for ${r.gallons} gal to folio ${r.folio_id}.`;
    case 'reserve_lane':
      return `Lap lane reserved — ${r.lap_lanes_open} lane(s) still open.`;
    case 'reserve_cabana':
      return `Cabana ${r.cabana} reserved for you (${r.day}).`;
    case 'join_clinic':
      return `Enrolled in ${r.clinic} — ${r.spots_open} spot(s) left.`;
    case 'cancel_tee_time':
      return `Tee time ${r.time} cancelled — the slot is free again.`;
    default:
      return JSON.stringify(r);
  }
}

async function resetAll(){
  await post('/api/reset', {});
  location.reload();
}

// ---------- tabs + portal / dashboard / status strip ----------
let STATE = null;
function switchTab(name){
  ['concierge','myclub','staff'].forEach(n => {
    el('tab-' + n).classList.toggle('hidden', n !== name);
    el('tab-b-' + n).classList.toggle('on', n === name);
  });
  if (name !== 'concierge') loadState();
}

async function loadState(){
  try {
    STATE = await (await fetch('/api/state')).json();
    renderStrip(STATE); renderMyClub(STATE); renderStaff(STATE); applyStanding();
  } catch(e){ /* leave last-known state */ }
}

// Suspend booking services when the signed-in member is not in good standing
// (mirrors the policy engine, which denies these tools per CC&R 9.1). Reads
// like the menu stay available.
let OVERRIDE = false;
function applyStanding(){
  if (!STATE) return;
  const m = STATE.member, good = m.standing === 'good', staff = STATE.role === 'staff';
  const banner = el('ac-suspend');
  banner.classList.toggle('hidden', good);
  if (!good){
    let html = `⊘ Club services suspended — <b>${m.name}</b> is not in good standing `
      + `(dues $${((m.dues && m.dues.balance) || 0).toFixed(2)} in arrears, CC&amp;R 9.1). `;
    html += staff
      ? `<label class="ovr"><input type="checkbox" id="ovr-chk" ${OVERRIDE ? 'checked' : ''} `
        + `onchange="toggleOverride()"> Manager override — book anyway (audited)</label>`
      : `Settle the balance to restore booking.`;
    banner.innerHTML = html;
  }
  // A suspended account locks the whole à la carte panel (menu included),
  // unless staff explicitly override.
  const waive = staff && OVERRIDE;
  document.querySelectorAll('#actions .act').forEach((row) => {
    const block = !good && !waive;
    row.classList.toggle('disabled', block);
    row.querySelectorAll('button, select, input').forEach(e => { e.disabled = block; });
  });
}
function toggleOverride(){ OVERRIDE = el('ovr-chk').checked; applyStanding(); }

function who(id, s){
  if (!id) return '<span class="free">open</span>';
  const nm = (s.names && s.names[id]) || id;
  return id === s.member_id ? `<span class="mineflag">${nm}</span>` : nm;
}
function sitem(k, v, cls){ return `<span class="sitem"><span class="sk">${k}</span><span class="sv ${cls||''}">${v}</span></span>`; }

function renderStrip(s){
  // Member account at a glance — NOT club inventory (lap lanes/cabanas live in
  // the Staff Portal, since they're facility-wide, not this member's).
  const m = s.member;
  const dues = (m.dues && m.dues.balance) || 0;
  el('strip').innerHTML =
    sitem('Standing', m.standing, m.standing !== 'good' ? 'warn' : '') +
    sitem('Dues', `$${dues.toFixed(2)}`, dues > 0 ? 'warn' : '') +
    sitem('Guest passes', `${m.passes_remaining} / ${m.passes_max}`) +
    sitem('Folio', `$${s.folio_total.toFixed(2)}`);
}

function renderMyClub(s){
  const m = s.member, dues = m.dues || {};
  el('mc-mono').textContent = initials(m.name);
  el('mc-name').textContent = m.name;
  el('mc-sub').textContent = `${m.tier} member · ${m.residence}`;
  const sb = el('mc-standing');
  sb.textContent = m.standing; sb.className = 'sbadge ' + (m.standing === 'good' ? 'good' : 'bad');
  const susp = el('mc-suspend'), good = m.standing === 'good';
  susp.classList.toggle('hidden', good);
  if (!good)
    susp.innerHTML = `⊘ <b>Account suspended.</b> Booking privileges are on hold until the `
      + `$${Number(dues.balance || 0).toFixed(2)} dues balance is settled (CC&amp;R 9.1). `
      + `Only HOA / dues actions remain available.`;
  el('mc-bookings').innerHTML = m.bookings.length
    ? m.bookings.map(b => `<div class="trow"><span class="k">${b.domain}</span><span>${b.detail}</span></div>`).join('')
    : '<div class="empty">No reservations yet — plan something in the Concierge tab.</div>';
  el('mc-passes').innerHTML =
    `<div class="trow"><span class="k">Remaining this year</span><span class="v">${m.passes_remaining} / ${m.passes_max}</span></div>
     <div class="trow"><span class="k">Max guests per visit</span><span class="v">${m.guests_per_visit_max}</span></div>
     <div class="trow"><span class="k">Registered guests</span><span class="v">${m.registered_guests.join(', ')}</span></div>`;
  el('mc-folio').innerHTML =
    `<div class="trow"><span class="k">Folio balance</span><span class="v">$${s.folio_total.toFixed(2)}</span></div>
     <div class="trow"><span class="k">Dues balance</span><span class="v">$${Number(dues.balance || 0).toFixed(2)}</span></div>
     <div class="trow"><span class="k">Next due</span><span class="v">${dues.next_due || '—'}</span></div>`;
  const p = m.preferences || {};
  el('mc-prefs').innerHTML = Object.keys(p).length
    ? Object.entries(p).map(([k,v]) => `<div class="trow"><span class="k">${k}</span><span>${v}</span></div>`).join('')
    : '<div class="empty">No preferences on file.</div>';
}

function renderStaff(s){
  el('st-golf').innerHTML = s.golf.map(t =>
    `<div class="slot"><span class="t">${t.time}</span><span>${t.slots} slots</span>
     <span class="who">${who(t.booked_by, s)}</span></div>`).join('');
  el('st-tennis').innerHTML =
    s.courts.map(c => `<div class="slot"><span class="t">${c.time}</span><span>${c.court}</span>
       <span class="who">${who(c.holder, s)}</span></div>`).join('') +
    s.clinics.map(cl => `<div class="slot"><span class="t">${cl.time}</span><span>${cl.name}</span>
       <span class="who">${cl.spots_open} spots · ${cl.roster.length} enrolled</span></div>`).join('');
  el('st-pool').innerHTML =
    `<div class="trow"><span class="k">Lap lanes open</span><span class="v">${s.lanes_open}</span></div>` +
    s.cabanas.map(c => `<div class="slot"><span class="t">${c.id}</span><span>cabana</span>
       <span class="who">${who(c.holder, s)}</span></div>`).join('');
  el('st-marina').innerHTML =
    `<div class="trow"><span class="k">Launch windows left</span><span class="v">${s.launch_windows.join(', ') || 'none'}</span></div>` +
    (s.fuel_charges.length ? s.fuel_charges.map(f =>
       `<div class="trow"><span class="k">Fuel · ${f.gallons} gal</span><span class="v">$${f.amount.toFixed(2)}</span></div>`).join('')
       : '<div class="empty">No fuel charges.</div>');
  let din = '';
  for (const [venue, slots] of Object.entries(s.dining)){
    din += `<div class="vhead">${venue}</div>` +
      slots.map(sl => `<div class="slot"><span class="t">${sl.time}</span><span>${sl.covers_open} covers open</span></div>`).join('');
  }
  if (s.folio.length)
    din += s.folio.map(f => `<div class="trow"><span class="k">${f.memo}</span><span class="v">$${f.amount.toFixed(2)}</span></div>`).join('');
  el('st-dining').innerHTML = din;
  el('st-hoa').innerHTML = s.arc_requests.length
    ? s.arc_requests.map(a => `<div class="trow"><span class="k">${a.modification}</span><span class="v">${a.status}</span></div>`).join('')
    : '<div class="empty">No ARC requests in the queue.</div>';
}

// ---------- login / persona ----------
let LOGIN_SEL = null;
function initials(name){ const p = name.trim().split(/\\s+/); return ((p[0]||'')[0]||'') + ((p[1]||'')[0]||''); }

let MEMBERS = [];
async function initApp(){
  const w = await (await fetch('/api/whoami')).json();
  MEMBERS = w.members || [];
  renderLogin(w.members);
}
function renderLogin(members){
  const box = el('lopts'); box.innerHTML = '';
  members.forEach((m, i) => {
    const opt = document.createElement('div');
    opt.className = 'lopt' + (i === 0 ? ' sel' : '');
    opt.onclick = () => selectLogin(opt, {role:'member', member_id:m.id});
    const st = m.standing !== 'good' ? `<span class="bad">${m.standing}</span>` : m.standing;
    opt.innerHTML = `<div class="mono">${initials(m.name)}</div>
      <div><div class="ln">${m.name}</div><div class="lmeta">${m.tier} · ${st}</div></div>`;
    box.appendChild(opt);
    if (i === 0) LOGIN_SEL = {role:'member', member_id:m.id};
  });
  const staff = document.createElement('div'); staff.className = 'lopt';
  staff.onclick = () => selectLogin(staff, {role:'staff', member_id:''});
  staff.innerHTML = `<div class="crest">S</div>
    <div><div class="ln">Club Staff</div><div class="lmeta">Operations portal</div></div>`;
  box.appendChild(staff);
}
function selectLogin(node, sel){
  document.querySelectorAll('.lopt').forEach(o => o.classList.remove('sel'));
  node.classList.add('sel'); LOGIN_SEL = sel;
}
async function doLogin(){
  if (!LOGIN_SEL) return;
  const w = await post('/api/login', LOGIN_SEL);
  el('login').classList.add('hidden');
  applyRole(w.role);
  await loadState();
  applyIdentity();
  renderWhoami(w);
}
function showLogin(){ el('login').classList.remove('hidden'); }
function renderWhoami(w){
  const label = w.role === 'staff' ? 'Club Staff' : w.name;
  el('whoami').innerHTML =
    `Signed in as <b>${label}</b> · ${w.role} — <a onclick="showLogin()">Switch user</a>`;
}
function applyRole(role){
  const staff = role === 'staff';
  // Staff get every tab (they book for members); members get concierge + my club.
  el('tab-b-concierge').classList.remove('hidden');
  el('tab-b-myclub').classList.remove('hidden');
  el('tab-b-staff').classList.toggle('hidden', !staff);
  el('actingbar').classList.toggle('hidden', !staff);
  if (staff) populateActing();
  switchTab(staff ? 'staff' : 'concierge');
}
function populateActing(){
  el('actingsel').innerHTML = MEMBERS.map(m =>
    `<option value="${m.id}">${m.name} · ${m.standing}</option>`).join('');
}
async function actAs(){
  OVERRIDE = false;   // a fresh member starts with no override
  await post('/api/act_as', {member_id: el('actingsel').value});
  await loadState(); applyIdentity();
}
function applyIdentity(){
  if (!STATE) return;
  const m = STATE.member, staff = STATE.role === 'staff';
  el('cc-mono').textContent = initials(m.name);
  el('cc-name').textContent = m.name;
  el('cc-res').textContent = `${m.tier} · ${m.residence}`;
  el('cc-flabel').textContent = staff
    ? `Plan for ${m.name.split(' ')[0]} — staff booking`
    : `What can I help you plan, ${m.name.split(' ')[0]}?`;
  el('cc-demonote').innerHTML = staff
    ? `<b>Staff</b> acting on behalf of <b>${m.name}</b> — bookings post to this member's account.`
    : `You're signed in as <b>${m.name}</b> — a seeded demo member; every club system is mock data.`;
  if (staff) el('actingsel').value = STATE.member_id;
}

buildActions();
initApp();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            ui_file = Path(__file__).resolve().parent / "ui.html"
            source = ui_file.read_text() if ui_file.exists() else INDEX_HTML
            html = source.replace("%DEFAULT_REQUEST%", json.dumps(DEFAULT_REQUEST))
            self._send(200, html.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/live/status":
            self._json(live_available())
        elif self.path == "/api/state":
            self._json(do_state())
        elif self.path == "/api/whoami":
            self._json(do_whoami())
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/api/propose":
                self._json(do_propose(self._read_json().get("request", "")))
            elif self.path == "/api/commit":
                body = self._read_json()
                self._json(do_commit(body.get("trace_id", ""), bool(body.get("approved")),
                                     body.get("edits")))
            elif self.path == "/api/action":
                body = self._read_json()
                self._json(do_action(body.get("tool", ""), body.get("args", {}),
                                     bool(body.get("confirmed")), bool(body.get("override"))))
            elif self.path == "/api/reset":
                self._json(do_reset())
            elif self.path == "/api/login":
                body = self._read_json()
                self._json(do_login(body.get("member_id", ""), body.get("role", "member")))
            elif self.path == "/api/act_as":
                self._json(do_act_as(self._read_json().get("member_id", "")))
            elif self.path == "/api/live/propose":
                self._json(do_live_propose(self._read_json().get("request", "")))
            elif self.path == "/api/live/confirm":
                body = self._read_json()
                self._json(do_live_confirm(body.get("session_id", ""), bool(body.get("approved"))))
            else:
                self._json({"error": "unknown endpoint"}, code=404)
        except Exception as err:  # keep the server alive; surface the error
            self._json({"error": f"{type(err).__name__}: {err}"}, code=500)

    def log_message(self, *args) -> None:  # quiet the default access log
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-open", action="store_true", help="don't auto-open the browser")
    args = parser.parse_args()

    _load_dotenv()
    url = f"http://localhost:{args.port}"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Viba concierge UI -> {url}  (Ctrl+C to stop)")
    if not args.no_open:
        try:
            webbrowser.get("chrome").open(url)  # prefer Chrome if registered
        except webbrowser.Error:
            webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        server.server_close()


if __name__ == "__main__":
    main()
