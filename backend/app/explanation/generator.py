"""Explanation generator: Ollama optional + deterministic template fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, cast

import httpx

from backend.app.core.config import Settings
from backend.app.explanation.faithfulness import validate_explanation_citations
from backend.app.explanation.templates import render_explanation

OllamaTransport = Callable[[str, dict[str, Any]], dict[str, Any]]


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("JSON must be object")
    return value


def generate_explanation(
    verified_payload: dict[str, Any],
    *,
    settings: Settings,
    transport: OllamaTransport | None = None,
) -> dict[str, Any]:
    """Return explanation dict; always citation-checked."""
    allowed_evidence = {str(item) for item in (verified_payload.get("evidence_ids") or [])}
    allowed_numbers = {
        f"{float(verified_payload.get('risk_score') or 0):.1f}",
        f"{float(verified_payload.get('confidence') or 0):.2f}",
        str(int(float(verified_payload.get("risk_score") or 0))),
    }
    allowed_rules = {
        str(item.get("rule_id"))
        for item in (verified_payload.get("contributing_signals") or [])
        if isinstance(item, dict) and item.get("rule_id")
    }

    template = render_explanation(verified_payload)
    if not settings.explanation_enabled:
        template["source"] = "disabled_template"
        return template

    if not settings.ollama_enabled and transport is None:
        return template

    active = transport
    if active is None and settings.ollama_enabled:

        def _default(prompt: str, extra: dict[str, Any]) -> dict[str, Any]:
            body = {
                "model": settings.ollama_model,
                "stream": False,
                "format": "json",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Explain verified fraud-investigation risk using only provided JSON. "
                            "Return JSON with summary, reasons, risk_level_explanation, "
                            "recommended_action_explanation, uncertainty_note, evidence_ids, "
                            "claims=[{claim, evidence_ids}]. Do not invent numbers or rules."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                **extra,
            }
            response = httpx.post(
                f"{settings.ollama_base_url.rstrip('/')}/api/chat",
                json=body,
                timeout=settings.ollama_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("bad ollama payload")
            return cast(dict[str, Any], payload)

        active = _default

    if active is None:
        return template

    prompt = json.dumps(verified_payload, sort_keys=True)
    last_error = "ollama_failed"
    for _ in range(2):
        try:
            raw = active(prompt, {})
            message = raw.get("message") or {}
            content = message.get("content") if isinstance(message, dict) else raw.get("response")
            if not isinstance(content, str):
                raise ValueError("missing content")
            draft = _extract_json(content)
            ok, problems = validate_explanation_citations(
                draft,
                allowed_evidence_ids=allowed_evidence,
                allowed_numbers=allowed_numbers,
                allowed_rule_ids=allowed_rules,
            )
            if ok:
                draft["source"] = "ollama"
                return draft
            last_error = ",".join(problems) or "citation_failed"
        except (ValueError, httpx.HTTPError, TypeError, KeyError) as exc:
            last_error = str(exc)

    template["source"] = "template_fallback"
    template["fallback_reason"] = last_error
    return template
