# Connectors spec (`CN`)

Implementation: `viba_concierge/mcp_servers/connectors.py`. One registry feeds
both the ADK FunctionTools and the FastMCP servers (`serve.py`), so these rules
hold on every transport. Connectors enforce **business rules**; the guardrail
layer (`GR`) enforces **who may act**. A connector rejection raises `ValueError`
and leaves the store unchanged.

### CN-01 Every tool declares its side effect
**Rule.** Each connector MUST be registered with a domain and a `side_effect`
flag. Reads MUST be `side_effect=False`; anything that books, reserves, charges or
drafts MUST be `side_effect=True`.
**Acceptance.**
- `charge_folio` and `book_tee_time` are side effects; `list_tee_times` and
  `check_guest_pass_eligibility` are not.
**Status.** enforced

### CN-02 Architecture verbs are all backed
**Rule.** Every tool verb shown in the architecture diagram MUST exist in the
registry and return real data.
**Acceptance.**
- The 17 diagram verbs (golf list/book/cancel, tennis courts/clinics, aquatics
  lanes/cabanas/guest passes, marina launch/fuel, dining table/folio/menu, HOA
  dues/ARC) are all registered; `get_menu("The Grill")` returns menu items.
**Status.** enforced

### CN-03 No double booking or overbooking
**Rule.** A resource already held (tee time, cabana) or without capacity (dining
covers) MUST be rejected.
**Acceptance.**
- A second booking of the same tee time fails with "not available".
- A party larger than remaining covers fails.
- Reserving an already-held cabana fails with "already reserved".
**Status.** enforced

### CN-04 Guest passes: registered guests only, allotment decrements
**Rule.** Passes MUST only be issued to guests registered on the member profile,
and each issued pass MUST decrement `guest_passes_remaining`.
**Acceptance.**
- An unregistered guest fails with "not registered".
- Issuing two passes reduces the balance by exactly two.
**Status.** enforced

### CN-05 Only the booking member may cancel
**Rule.** `cancel_tee_time` MUST reject any member other than the holder.
**Acceptance.**
- Another member's cancel fails; the holder's cancel frees the slot.
**Status.** enforced

### CN-06 Reservations consume inventory
**Rule.** Clinic spots and lap lanes MUST decrement on reservation; a member MUST
NOT enroll twice in one clinic.
**Acceptance.**
- Joining a clinic reduces `spots_open` by one and adds the member to the roster;
  a second join fails with "already enrolled".
- Reserving a lane reduces `lap_lanes_open` by one.
**Status.** enforced

### CN-07 Fuel is priced from the ledger
**Rule.** `log_fuel` MUST charge `gallons × fuel_price_per_gal`, rounded to cents,
and record it on the marina ledger.
**Acceptance.**
- Logging 10 gallons posts one charge of `round(10 × price, 2)`.
**Status.** enforced

### CN-08 ARC requests are drafted, never submitted
**Rule.** `draft_arc_request` MUST create a record with status
`DRAFT - not submitted`. No tool may submit to the committee on the member's behalf.
**Acceptance.**
- After an approved itinerary, the stored ARC request status starts with `DRAFT`.
**Status.** enforced
