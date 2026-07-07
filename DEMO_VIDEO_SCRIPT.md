# Viba Concierge — YouTube Demo Script (≤ 5:00)

**Target: ~4:15 spoken, safely under the 5-minute cap.** Covers all five rubric beats: **Problem · Why agents · Architecture · Demo · The Build.** Track: **Concierge Agents**.

**Recording surfaces (all deterministic, no API key — timing never surprises you):**
- Browser app — `python3 scripts/webapp.py` → `http://localhost:8000` (main demo surface: itinerary cards, the confirmation gate as a real control, live audit table)
- Terminal — `python scripts/demo.py` and `python -m pytest tests/ -q` for the proof shots
- The architecture diagram image for the architecture beat

Record clean video first, then lay the voiceover. Word counts per section keep you on pace (~150 wpm).

---

### 1 · Problem — 0:00–0:40  *(~95 words)*

**On screen:** the architecture diagram, or a split of six club logos / six login screens.

**VO:** "A luxury residential club runs on six completely separate systems — a golf tee sheet, a tennis grid, a marina ledger, an aquatics registry, a dining POS, and an HOA portal. Six logins, six rulebooks. But a member doesn't think in systems. She thinks in one sentence: *plan my Saturday — golf, lunch, tennis, sunset on the boat, can my guests use the pool, and can I paint my front door navy?* That one request touches all six systems, mixes booking with money with governance — and no form on earth could ever capture it."

---

### 2 · Why agents — 0:40–1:15  *(~85 words)*

**On screen:** the sentence, with six labelled arrows fanning out to six domain boxes.

**VO:** "This is exactly what agents are for. The request has to be *decomposed* into six intents, each *reasoned* against live availability, entitlements, and the governing documents, then *chained* into one coherent plan — and paused for a human before any money moves. That's planning, tool use, and judgment across domains. A single prompt can't hold it safely. So Viba uses a multi-agent system: one orchestrator, six specialists, one shared memory — and one guardrail every action must pass through."

---

### 3 · Architecture — 1:15–2:00  *(~110 words)*

**On screen:** the six-layer architecture diagram, highlighting each layer as named.

**VO:** "Six layers. At the top, the member surface — a CLI, a web app, or a live Gemini agent. Below it, the orchestrator and a shared member profile. Then the layer that matters most: the guardrails — a single PolicyEngine that every delegation and every tool call passes through. Under that, six domain sub-agents. They call a tool layer of twenty functions, exposed both as ADK function-tools and as six MCP servers over stdio — one registry, no forks. And at the bottom, eight seeded members and their systems of record. The rule the whole design enforces: sub-agents *propose*; they never commit."

---

### 4 · Demo — 2:00–3:30  *(~210 words)*

**On screen:** the browser app, signed in as Eleanor. Type nothing — the request is pre-filled. Click **Plan**.

**VO:** "Here it is live. One request. It decomposes into six intents and delegates to six agents over her shared profile — and watch: each proposal is shaped to *her* preferences. Morning tee time. A window table. Her own slip at the marina."

**On screen:** the two FINDINGS lines with citations.

**VO:** "The two questions aren't guessed. Guests at the pool — eligible, six passes left, cited to club rule seven-one. Navy door — on the pre-approved palette, cited to the CC&Rs. Grounded in the governing documents, citation shown."

**On screen:** the **GATE ACTIVE** banner and the audit table — every row `NEEDS_CONFIRMATION`.

**VO:** "And now the point of the whole system. Six actions proposed — none of them have run. The audit already shows a needs-confirmation row for every side effect. Nothing is booked, nothing is charged, until Eleanor clicks Confirm." *(click Confirm — rows flip to committed; zoom the HOA line)* "Now they commit — and the HOA request stays a draft. Governance decisions stay with the member."

**On screen:** switch to **staff** login → act-as delinquent member → booking denied (CC&R 9.1) → toggle **override** → allowed, audit row shows `override: true`.

**VO:** "Change the actor. A delinquent member is blocked by the standing gate. Only staff can waive it — and the waiver is logged as an override, cited, and it still cannot touch a charge."

---

### 5 · The Build — 3:30–4:15  *(~110 words)*

**On screen:** a fast scroll of the repo tree, then a terminal: `python -m pytest tests/ -q` → **32 passed**.

**VO:** "How it's built: Python and Google's Agent Development Kit for the live agents, FastMCP for the six MCP servers, and a deterministic rule-based core so the entire thing — and its thirty-two tests — runs with no API key. The same PolicyEngine that guards the CLI is attached as a before-tool callback on the live Gemini agent, so no model output can route around it. And the safety claims aren't asserted on mocks — they're asserted on state. Thirty-two tests hold the line: never auto-charge, override-only-by-staff, zero side effects on decline."

**On screen:** run `python scripts/demo.py --decline` → "zero side effects."

**VO:** "One request. Six clubs. No forms — and nothing happens until the member says yes."

**End card:** `Viba Club Concierge · Concierge track · ADK · MCP · RAG · Guardrails · Shared memory`

---

## Shot list

| Beat | Time | Surface / command |
|---|---|---|
| Problem | 0:00 | diagram / six-login split |
| Why agents | 0:40 | fan-out animation over the request |
| Architecture | 1:15 | six-layer diagram, layer highlights |
| Demo — plan & findings | 2:00 | `webapp.py` → **Plan**, scroll to citations |
| Demo — the gate | 2:40 | GATE ACTIVE + audit table → **Confirm** |
| Demo — override | 3:05 | staff login → act-as delinquent → override toggle |
| The Build | 3:30 | repo scroll + `pytest -q` → 32 passed |
| Close | 4:00 | `demo.py --decline` → zero side effects + end card |

**Production notes**
- Everything is deterministic and needs no key, so retakes reproduce exactly. If you record live Gemini mode via the web app's live toggle and latency lags, the dry-run recording is a drop-in substitute with identical beats.
- Publish **unlisted or public on YouTube** and attach the link in the Kaggle Media Gallery. Keep total runtime **≤ 5:00** — this script leaves ~45s of headroom for pauses.
- Add captions/on-screen labels for each audit verdict; judges scan fast.
