# Governing-documents RAG spec (`RG`)

Implementation: `viba_concierge/core/governing_docs.py` (`TfidfRetriever`,
`ask_governing_docs`). The `Retriever` protocol lets production swap in
embeddings; these requirements MUST keep holding after that swap.

### RG-01 Policy answers carry citations
**Rule.** Every governing-document answer MUST return citations with `doc_id`,
title, snippet and score, and the right clause MUST be among them.
**Acceptance.**
- "can I repaint my front door navy" cites `ccr-4.2` (Architectural Review).
- "can my guests use the pool guest pass" cites `club-7.1` (Guest Privileges).
**Status.** enforced

### RG-02 Results are ranked and non-empty-scored
**Rule.** Citations MUST be ordered by descending score; zero-score documents
MUST NOT be returned.
**Acceptance.**
- For "guest pass pool", `k=3` scores are sorted descending.
**Status.** enforced

### RG-03 Agents scope retrieval to their own question
**Rule.** A domain agent MUST query with its own intent, not the member's whole
multi-intent request, so another domain's wording cannot win retrieval.
**Acceptance.**
- For Eleanor's six-part request, the HOA proposal cites `ccr-4.2` and not
  `club-3.4` (Golf Guest Policy), and notes that Classic Navy is on the
  pre-approved palette.
**Status.** enforced
