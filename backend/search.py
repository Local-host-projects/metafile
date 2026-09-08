"""
Minimal TF-IDF search with cosine similarity.

This stands in for a real embeddings-based semantic search. It's a
drop-in seam: swap `_vectorize` for a call to an embeddings API/model
and everything downstream (indexing, cosine ranking, batching) keeps
working unchanged. Kept dependency-free and local so the demo doesn't
need network access to an embeddings provider.
"""
import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str):
    return _TOKEN_RE.findall(text.lower())


def _vectorize(tokens, idf):
    tf = Counter(tokens)
    total = sum(tf.values()) or 1
    return {t: (c / total) * idf.get(t, 0.0) for t, c in tf.items()}


def _cosine(a: dict, b: dict) -> float:
    keys = set(a) & set(b)
    num = sum(a[k] * b[k] for k in keys)
    da = math.sqrt(sum(v * v for v in a.values())) or 1e-9
    db = math.sqrt(sum(v * v for v in b.values())) or 1e-9
    return num / (da * db)


def search_facts(facts: list, query: str, limit: int = 10, offset: int = 0):
    """
    facts: list of {"id":..., "text":..., "tags":[...]}
    Returns ranked (fact, score) pairs, batched by limit/offset so an
    agent can consume results a page at a time instead of all at once.
    """
    if not facts:
        return [], 0

    docs = [f["text"] + " " + " ".join(f.get("tags", [])) for f in facts]
    doc_tokens = [_tokenize(d) for d in docs]

    df = Counter()
    for toks in doc_tokens:
        for t in set(toks):
            df[t] += 1
    n_docs = len(docs)
    idf = {t: math.log((n_docs + 1) / (c + 1)) + 1 for t, c in df.items()}

    doc_vecs = [_vectorize(toks, idf) for toks in doc_tokens]
    q_vec = _vectorize(_tokenize(query), idf)

    scored = [
        (facts[i], _cosine(q_vec, doc_vecs[i]))
        for i in range(n_docs)
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    total = len(scored)
    page = scored[offset:offset + limit]
    return page, total
