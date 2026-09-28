# Membership tiers spec (`TR`)

Implementation: `TIER_BENEFITS` and `tier_entitlements()` in
`viba_concierge/mcp_servers/seed_data.py`. Enforcement lives in `GR-07`
(entitlements) and `GR-08` (weekend days); this spec defines what each tier grants.

| Tier | Golf | Pool | Dining | Tennis | Marina | Annual guest passes | Weekend days |
|---|---|---|---|---|---|---|---|
| Silver | ✓ | ✓ | ✓ | – | – | 2 | none |
| Gold | ✓ | ✓ | ✓ | ✓ | – | 4 | Saturday |
| Platinum | ✓ | ✓ | ✓ | ✓ | ✓ | 6 | Saturday, Sunday |

### TR-01 Tier is the single source of facility entitlements
**Rule.** A member's facility entitlements MUST be derived from their tier per the
table above, not set independently.
**Acceptance.**
- Silver has golf/pool/dining but not tennis/marina; Gold adds tennis but not
  marina; Platinum has all five.
- A Silver member scheduling a marina launch is denied, reason names `marina`.
**Status.** enforced

### TR-02 Tier sets the guest-pass allotment
**Rule.** Annual passes MUST be 2 / 4 / 6 for Silver / Gold / Platinum, and a
member's balance MUST be clamped to their tier's allotment at load.
**Acceptance.**
- `TIER_BENEFITS` allotments match the table; a Silver balance is ≤ 2.
**Status.** enforced
