"""RAG over the governing documents (CC&Rs, club rules, marina rules).

Deterministic TF-IDF retrieval with cosine similarity; no external service or
API key needed, so the demo and tests run anywhere. The retriever returns
citation objects (doc_id, title, snippet, score) that agents must attach to
any policy claim, so every answer about "am I allowed to..." is grounded.

Swap `TfidfRetriever` for an embedding-backed retriever in production; the
`Retriever` protocol keeps the agents unchanged.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from ..mcp_servers.seed_data import GOVERNING_DOCS
from ..observability.logging import get_logger, span

log = get_logger("viba.rag")

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "is", "are", "be",
         "for", "with", "by", "on", "at", "any", "all", "not", "no", "shall",
         "may", "must", "their", "its"}


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@dataclass
class Citation:
    doc_id: str
    title: str
    snippet: str
    score: float

    def cite(self) -> str:
        return f"[{self.doc_id}] {self.title}"


class Retriever(Protocol):
    def search(self, query: str, k: int = 2) -> list[Citation]: ...


class TfidfRetriever:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = docs or GOVERNING_DOCS
        self._doc_tokens = [_tokens(d["title"] + " " + d["text"]) for d in self.docs]
        n = len(self.docs)
        df: Counter = Counter()
        for toks in self._doc_tokens:
            df.update(set(toks))
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        self._doc_vecs = [self._vec(toks) for toks in self._doc_tokens]

    def _vec(self, toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        total = max(len(toks), 1)
        return {t: (c / total) * self._idf.get(t, 1.0) for t, c in tf.items()}

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        common = set(a) & set(b)
        num = sum(a[t] * b[t] for t in common)
        den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
        return num / den if den else 0.0

    def search(self, query: str, k: int = 2) -> list[Citation]:
        with span("rag.search", query=query[:80]):
            q = self._vec(_tokens(query))
            scored = sorted(
                ((self._cosine(q, dv), i) for i, dv in enumerate(self._doc_vecs)),
                reverse=True,
            )
            results = []
            for score, i in scored[:k]:
                if score <= 0.0:
                    continue
                doc = self.docs[i]
                snippet = doc["text"][:220] + ("..." if len(doc["text"]) > 220 else "")
                results.append(Citation(doc["doc_id"], doc["title"], snippet, round(score, 4)))
            log.info("rag.results", extra={"hits": [c.doc_id for c in results]})
            return results


_default: TfidfRetriever | None = None


def default_retriever() -> TfidfRetriever:
    global _default
    if _default is None:
        _default = TfidfRetriever()
    return _default


def ask_governing_docs(question: str, k: int = 2) -> dict:
    """Tool-shaped entry point: retrieve grounded citations for a policy question."""
    cites = default_retriever().search(question, k=k)
    return {
        "question": question,
        "citations": [
            {"doc_id": c.doc_id, "title": c.title, "snippet": c.snippet, "score": c.score}
            for c in cites
        ],
    }
