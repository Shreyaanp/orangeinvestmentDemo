"""Opt-in hybrid retrieval over past incidents: BM25 and dense cosine fused by reciprocal rank,
then a cross-encoder rerank of the top candidates.

Off by default: with RETRIEVAL unset (or "keyword") callers keep their keyword scoring unchanged.
RETRIEVAL=hybrid uses fastembed (local ONNX models; one download, then offline; `pip install
.[retrieval]`). RETRIEVAL=fake uses deterministic hashed vectors (tests and offline demos).
"""

import hashlib
import math
import os
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Protocol

DENSE_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
RRF_K = 60
MODES = ("keyword", "hybrid", "fake")


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{3,}", text.lower())


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    def score(self, query: str, docs: Sequence[str]) -> list[float]:
        """Relevance of each doc to the query, in [0, 1]."""
        ...


def _unit(v: Sequence[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else list(v)


def _stem(word: str) -> str:
    return word[:5]  # a crude prefix stem: "throttled" and "throttling" collapse


class FakeEmbedder:
    """Hashed bag of stems and character trigrams: deterministic, offline, no model."""

    dim = 512

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for w in tokens(text):
                for feat in (_stem(w), *(w[i : i + 3] for i in range(len(w) - 2))):
                    h = hashlib.blake2b(feat.encode(), digest_size=4).digest()
                    v[int.from_bytes(h, "big") % self.dim] += 1.0
            out.append(_unit(v))
        return out


class FakeReranker:
    """Share of the query's stems found in the doc."""

    def score(self, query: str, docs: Sequence[str]) -> list[float]:
        want = {_stem(w) for w in tokens(query)}
        return [len(want & {_stem(w) for w in tokens(d)}) / (len(want) or 1) for d in docs]


class FastEmbedder:
    def __init__(self, model: str = DENSE_MODEL) -> None:
        from fastembed import TextEmbedding

        self._model: Any = TextEmbedding(model_name=model)
        self._cache: dict[str, list[float]] = {}

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        new = [t for t in dict.fromkeys(texts) if t not in self._cache]
        for t, v in zip(new, self._model.embed(new), strict=True):
            self._cache[t] = _unit([float(x) for x in v])
        return [self._cache[t] for t in texts]


class FastReranker:
    def __init__(self, model: str = RERANK_MODEL) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model: Any = TextCrossEncoder(model_name=model)

    def score(self, query: str, docs: Sequence[str]) -> list[float]:
        logits = self._model.rerank(query, list(docs))
        return [1.0 / (1.0 + math.exp(-float(s))) for s in logits]


def bm25(query: str, docs: Sequence[str], k1: float = 1.2, b: float = 0.75) -> list[float]:
    toks = [tokens(d) for d in docs]
    avg = sum(map(len, toks)) / len(toks) or 1.0
    df = Counter(w for t in toks for w in set(t))
    want = set(tokens(query))
    out = []
    for t in toks:
        tf, s = Counter(t), 0.0
        for w in want & tf.keys():
            idf = math.log(1 + (len(docs) - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avg))
        out.append(s)
    return out


def rrf(score_lists: Sequence[Sequence[float]]) -> list[float]:
    """Reciprocal rank fusion; a zero score contributes nothing (that list did not find it)."""
    fused = [0.0] * len(score_lists[0])
    for scores in score_lists:
        order = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: -scores[i])
        for rank, i in enumerate(order):
            fused[i] += 1.0 / (RRF_K + rank + 1)
    return fused


@dataclass
class Retriever:
    embedder: Embedder
    reranker: Reranker | None = None
    top_k: int = 10  # candidates passed to the reranker
    min_relevance: float = 0.3  # a candidate with no shared keyword must clear this

    def rank(self, query: str, docs: Sequence[str]) -> list[tuple[int, float]]:
        """(doc index, relevance in [0, 1]) for matching docs, best first."""
        if not docs:
            return []
        lexical = bm25(query, docs)
        q, *vecs = self.embedder.embed([query, *docs])
        dense = [max(0.0, sum(a * b for a, b in zip(q, v, strict=True))) for v in vecs]
        fused = rrf([lexical, dense])
        cands = sorted((i for i in range(len(docs)) if fused[i] > 0), key=lambda i: -fused[i])
        cands = cands[: self.top_k]
        rel = (
            self.reranker.score(query, [docs[i] for i in cands])
            if self.reranker
            else [dense[i] for i in cands]
        )
        kept = [
            (i, r)
            for i, r in zip(cands, rel, strict=True)
            if lexical[i] > 0 or r >= self.min_relevance
        ]
        return sorted(kept, key=lambda x: -x[1]) if self.reranker else kept


def build(mode: str | None = None) -> Retriever | None:
    """None means keyword search (the default). mode None reads the RETRIEVAL env var."""
    return _build((mode or os.environ.get("RETRIEVAL") or "keyword").strip().lower())


def hybrid_order(query: str, docs: Sequence[str]) -> list[int] | None:
    """Doc indices best first, or None when retrieval is not opted in (callers use keywords)."""
    r = build()
    return None if r is None else [i for i, _ in r.rank(query, docs)]


@cache
def _build(mode: str) -> Retriever | None:
    if mode not in MODES:
        raise ValueError(f"RETRIEVAL must be one of {MODES}, got {mode!r}")
    if mode == "hybrid":
        return Retriever(FastEmbedder(), FastReranker())
    return Retriever(FakeEmbedder(), FakeReranker()) if mode == "fake" else None
