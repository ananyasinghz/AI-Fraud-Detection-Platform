"""ChromaDB (or local sklearn) policy index with deterministic HashingVectorizer embeddings."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, cast

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from backend.app.tools.retrieval.corpus import corpus_fingerprint, load_corpus

COLLECTION_NAME = "policy_excerpts_v1"
EMBED_DIM = 384


class HashingEmbedder:
    """Deterministic local embeddings — no model download."""

    def __init__(self) -> None:
        self._vectorizer = HashingVectorizer(
            n_features=EMBED_DIM,
            alternate_sign=False,
            norm="l2",
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        matrix = self._vectorizer.transform(texts)
        dense = np.asarray(matrix.todense(), dtype=np.float32)
        return cast(list[list[float]], dense.tolist())


def ensure_policy_index(
    *,
    corpus_path: Path,
    persist_dir: Path,
) -> dict[str, Any]:
    """Build or reuse the policy index; returns a handle dict for search_policy."""
    fingerprint = corpus_fingerprint(corpus_path)
    persist_dir.mkdir(parents=True, exist_ok=True)
    meta_path = persist_dir / "index_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("fingerprint") == fingerprint and meta.get("backend"):
            return {"persist_dir": persist_dir, "fingerprint": fingerprint, **meta}

    documents = load_corpus(corpus_path)
    embedder = HashingEmbedder()
    texts = [doc["text"] for doc in documents]
    vectors = embedder.embed(texts)

    backend = "local_sklearn"
    try:
        _build_chroma(persist_dir, documents, vectors)
        backend = "chromadb"
    except Exception:
        # Honest local fallback when chromadb is unavailable in the environment.
        _build_local(persist_dir, documents, vectors)

    meta = {
        "fingerprint": fingerprint,
        "backend": backend,
        "doc_count": len(documents),
        "collection": COLLECTION_NAME,
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return {"persist_dir": persist_dir, **meta}


def search_policy(
    *,
    corpus_path: Path,
    persist_dir: Path,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    handle = ensure_policy_index(corpus_path=corpus_path, persist_dir=persist_dir)
    embedder = HashingEmbedder()
    query_vec = np.asarray(embedder.embed([query])[0], dtype=np.float32).reshape(1, -1)

    if handle.get("backend") == "chromadb":
        with contextlib.suppress(Exception):
            return _search_chroma(persist_dir, query_vec, top_k)
    return _search_local(persist_dir, query_vec, top_k)


def _build_chroma(
    persist_dir: Path,
    documents: list[dict[str, Any]],
    vectors: list[list[float]],
) -> None:
    import chromadb

    client = chromadb.PersistentClient(path=str(persist_dir / "chroma"))
    with contextlib.suppress(Exception):
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    collection.add(
        ids=[doc["doc_id"] for doc in documents],
        documents=[doc["text"] for doc in documents],
        embeddings=cast(Any, vectors),
        metadatas=[
            {
                "title": doc["title"],
                "source_url": doc["source_url"],
                "publication_date": doc["publication_date"],
                "jurisdiction": doc["jurisdiction"],
                "section": doc["section"],
            }
            for doc in documents
        ],
    )


def _search_chroma(persist_dir: Path, query_vec: np.ndarray, top_k: int) -> list[dict[str, Any]]:
    import chromadb

    client = chromadb.PersistentClient(path=str(persist_dir / "chroma"))
    collection = client.get_collection(COLLECTION_NAME)
    result = collection.query(
        query_embeddings=cast(Any, query_vec.tolist()),
        n_results=top_k,
        include=cast(Any, ["documents", "metadatas", "distances"]),
    )
    hits: list[dict[str, Any]] = []
    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]
    for index, doc_id in enumerate(ids):
        meta = metas[index] if index < len(metas) else {}
        distance = float(dists[index]) if index < len(dists) else 1.0
        hits.append(
            {
                "doc_id": doc_id,
                "title": meta.get("title"),
                "source_url": meta.get("source_url"),
                "publication_date": meta.get("publication_date"),
                "jurisdiction": meta.get("jurisdiction"),
                "section": meta.get("section"),
                "snippet": docs[index] if index < len(docs) else "",
                "score": max(0.0, 1.0 - distance),
            }
        )
    return hits


def _build_local(
    persist_dir: Path,
    documents: list[dict[str, Any]],
    vectors: list[list[float]],
) -> None:
    payload = {
        "documents": documents,
        "vectors": vectors,
    }
    (persist_dir / "local_index.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _search_local(persist_dir: Path, query_vec: np.ndarray, top_k: int) -> list[dict[str, Any]]:
    payload = json.loads((persist_dir / "local_index.json").read_text(encoding="utf-8"))
    documents = payload["documents"]
    matrix = np.asarray(payload["vectors"], dtype=np.float32)
    scores = cosine_similarity(query_vec, matrix)[0]
    order = np.argsort(-scores)[:top_k]
    hits: list[dict[str, Any]] = []
    for index in order:
        doc = documents[int(index)]
        hits.append(
            {
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "source_url": doc["source_url"],
                "publication_date": doc["publication_date"],
                "jurisdiction": doc["jurisdiction"],
                "section": doc["section"],
                "snippet": doc["text"],
                "score": float(scores[int(index)]),
            }
        )
    return hits
