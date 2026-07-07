"""Anchor demo: Eleanor's Saturday, end to end.

    python scripts/demo.py            # propose -> pause -> confirm -> commit
    python scripts/demo.py --decline  # member declines at the gate
    python scripts/demo.py --json     # machine-readable output

Shows all five course concepts in one run: multi-agent orchestration, MCP-shaped
tools, RAG citations, the guardrail confirmation gate, and shared member memory.
Structured JSON traces stream to stderr; the member-facing story prints to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from viba_concierge.core.orchestrator import ConciergeOrchestrator
from viba_concierge.mcp_servers.seed_data import reset_store
from viba_concierge.core.logging import configure

ELEANOR_REQUEST = (
    "Plan Saturday for me and three guests - morning golf, lunch at the Grill, "
    "afternoon tennis, sunset on the boat. Can my guests use the pool? "
    "Also, I'd like to repaint my front door navy - am I allowed?"
)

RULE = "-" * 72


def run(approve: bool, as_json: bool) -> int:
    configure()
    reset_store()
    orchestrator = ConciergeOrchestrator(member_id="M-1014")

    result = orchestrator.propose(ELEANOR_REQUEST)

    if not as_json:
        print(RULE)
        print("MEMBER REQUEST (Eleanor R.)")
        print(f'  "{ELEANOR_REQUEST}"')
        print(RULE)
        print(f"TRACE {result.trace_id} - PROPOSED ITINERARY "
              f"({len(result.itinerary)} actions, none committed)")
        for i, item in enumerate(result.itinerary, 1):
            print(f"  {i}. [{item.domain:>6}] {item.proposal}")
        print("\nFINDINGS")
        for note in result.notes:
            print(f"  - {note}")
        print("\nGATE ACTIVE: paused for member confirmation. Nothing booked, "
              "nothing charged.")
        print(RULE)

    result = orchestrator.commit(result, approved=approve)

    if as_json:
        print(json.dumps({
            "trace_id": result.trace_id,
            "approved": approve,
            "itinerary": [
                {"domain": i.domain, "tool": i.tool, "status": i.status,
                 "proposal": i.proposal, "result": i.result}
                for i in result.itinerary
            ],
            "notes": result.notes,
            "blocked": result.blocked,
            "audit": result.audit,
        }, indent=2, default=str))
        return 0

    if approve:
        print(f"MEMBER CONFIRMED - committing {len(result.itinerary)} actions")
        for item in result.itinerary:
            marker = "OK " if item.status == "committed" else "ERR"
            print(f"  {marker} {item.tool:<28} -> {item.status}")
        if result.blocked:
            print("\nBLOCKED BY GUARDRAILS")
            for line in result.blocked:
                print(f"  - {line}")
    else:
        print("MEMBER DECLINED - itinerary discarded, zero side effects")

    print(RULE)
    print("AUDIT TRAIL (PII redacted)")
    for line in result.audit:
        print(f"  {line}")
    print(RULE)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--decline", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(approve=not args.decline, as_json=args.json))
