# Specs: spec-driven development for Viba Concierge

The files in this directory are the **source of truth for behavior**. `DESIGN.md`
explains *why* the system is shaped the way it is; these specs state *what it must
do*, in terms a test can check. Code serves the spec, tests prove the spec, and a
traceability test keeps the three from drifting apart.

| Spec | Prefix | Covers |
|---|---|---|
| [guardrails.md](guardrails.md) | `GR` | PolicyEngine verdicts, confirmation gate, never-auto-charge, PII, audit |
| [connectors.md](connectors.md) | `CN` | Tool registry and the business rules each connector enforces |
| [tiers.md](tiers.md) | `TR` | Membership tier as the source of entitlements and guest-pass limits |
| [rag.md](rag.md) | `RG` | Governing-document retrieval and mandatory citations |
| [orchestration.md](orchestration.md) | `OR` | Propose → gate → commit/decline pipeline and shared memory |
| [observability.md](observability.md) | `OB` | Structured logs, trace propagation, spans, error capture |
| [live-mode.md](live-mode.md) | `LV` | Guardrail parity when Gemini/ADK agents drive the tools |

## Requirement format

```markdown
### GR-02 Charge tools never auto-fire
**Rule.** One sentence, testable, uses MUST / MUST NOT.
**Acceptance.**
- Given <state>, when <action>, then <observable outcome>.
**Status.** enforced | planned
```

- IDs are permanent. Never renumber or reuse one; retire a requirement by setting
  `**Status.** retired` and leaving the heading in place.
- `enforced` requirements MUST have at least one test tagged with their ID.
- `planned` requirements are accepted scope with no implementation yet; they are
  exempt from the coverage check until promoted to `enforced`.
- Acceptance criteria assert **outcomes and state** (the store, the audit trail,
  the verdict), never internals or mocks.

## Linking tests to requirements

```python
@pytest.mark.spec("GR-02", "GR-10")
def test_charge_never_fires_without_confirmation(): ...
```

`tests/test_spec_traceability.py` fails the build when:

1. an `enforced` requirement has no test tagged with its ID, or
2. a test is tagged with an ID that no spec defines (typo or retired rule).

Run it alone with `pytest tests/test_spec_traceability.py -v`; run the full
matrix report with `python -m tests.test_spec_traceability`.

## Workflow for any change

1. **Spec first.** Add or edit the requirement (new ID, `Status: planned`). A
   reviewer can approve the behavior before any code exists.
2. **Test second.** Write the failing test, tag it with the ID.
3. **Code third.** Make it pass; flip the status to `enforced`.
4. **Docs last.** If the change alters a design decision, update `DESIGN.md` so
   it never contradicts the spec.

Bug fixes follow the same loop: first ask "which requirement did this violate?"
If none, the spec had a gap; add the requirement, then the regression test.
