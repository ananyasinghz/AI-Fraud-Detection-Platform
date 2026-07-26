"""Load and validate the committed policy excerpt corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = (
    "doc_id",
    "title",
    "source_url",
    "publication_date",
    "jurisdiction",
    "section",
    "text",
)


def load_corpus(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "documents" not in payload:
        raise ValueError("policy corpus must be a JSON object with documents[]")
    documents = payload["documents"]
    if not isinstance(documents, list) or not documents:
        raise ValueError("policy corpus documents must be a non-empty list")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in documents:
        if not isinstance(item, dict):
            raise ValueError("each corpus document must be an object")
        missing = [field for field in REQUIRED_FIELDS if field not in item]
        if missing:
            raise ValueError(f"corpus document missing fields: {', '.join(missing)}")
        doc_id = str(item["doc_id"])
        if doc_id in seen:
            raise ValueError(f"duplicate corpus doc_id: {doc_id}")
        seen.add(doc_id)
        validated.append(
            {
                "doc_id": doc_id,
                "title": str(item["title"]),
                "source_url": str(item["source_url"]),
                "publication_date": str(item["publication_date"]),
                "jurisdiction": str(item["jurisdiction"]),
                "section": str(item["section"]),
                "text": str(item["text"]),
            }
        )
    return validated


def corpus_fingerprint(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:24]
