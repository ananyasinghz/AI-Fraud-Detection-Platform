"""Policy retrieval tool — reviewer context only, never legal conclusions."""

from __future__ import annotations

from typing import Any

from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import ToolProvenance
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import Timer, make_result
from backend.app.tools.retrieval.index import search_policy


def handle_retrieval(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> Any:
    timer = Timer()
    provenance = ToolProvenance(
        source="retrieval",
        query_or_version="retrieval.v1",
        policy_version=context.policy.version,
    )
    if not context.settings.retrieval_enabled:
        return make_result(
            tool=ToolName.RETRIEVAL,
            operation=operation,
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=["RETRIEVAL_DISABLED"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )
    if operation != "search_policy":
        raise ValueError(f"unknown retrieval operation: {operation}")

    query = str(parameters.get("query") or parameters.get("text") or "").strip()
    if not query:
        return make_result(
            tool=ToolName.RETRIEVAL,
            operation=operation,
            status=ToolStatus.SUCCESS,
            scope=context.filters,
            data={"hits": [], "count": 0},
            warnings=["EMPTY_QUERY", "POLICY_CONTEXT_ONLY"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    top_k = int(parameters.get("top_k") or context.settings.retrieval_top_k)
    top_k = max(1, min(top_k, 20))
    corpus_path = context.settings.policy_corpus_path
    if not corpus_path.is_file():
        return make_result(
            tool=ToolName.RETRIEVAL,
            operation=operation,
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=["CORPUS_MISSING", "POLICY_CONTEXT_ONLY"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    hits = search_policy(
        corpus_path=corpus_path,
        persist_dir=context.settings.chroma_persist_dir,
        query=query,
        top_k=top_k,
    )
    return make_result(
        tool=ToolName.RETRIEVAL,
        operation=operation,
        status=ToolStatus.SUCCESS,
        scope=context.filters,
        data={
            "hits": hits,
            "count": len(hits),
            "disclaimer": (
                "Retrieved policy text is reviewer context only; "
                "it must not override deterministic evidence or present legal conclusions."
            ),
        },
        warnings=["POLICY_CONTEXT_ONLY"],
        duration_ms=timer.ms(),
        provenance=provenance,
    )
