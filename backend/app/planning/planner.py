"""Ollama-backed dynamic planner with one retry and safe template fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.domain.intent import ParsedIntent
from backend.app.domain.plan import ValidatedPlan
from backend.app.planning.fallback import safe_template_for_intent
from backend.app.planning.schemas import catalog_prompt_block
from backend.app.planning.validator import ValidationResult, validate_plan_semantics

OllamaTransport = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class PlannerResult:
    plan: ValidatedPlan | None
    source: str
    rejection_reasons: tuple[str, ...] = ()
    used_fallback: bool = False


_SYSTEM_PROMPT = f"""You are a fraud-investigation planner. Output JSON only.
Return one object: {{"strategy": string, "steps": [{{
  "step_id": string, "tool": string, "operation": string,
  "parameters": object, "depends_on": string[], "reason": string, "required": bool
}}]}}
Rules:
- Prefer minimal plans; never run every tool.
- SQL-only and feature-only questions must not include risk tiers, EDA, or Phase 8 tools.
- Suspicious/entity/scoring paths may use verification → risk_classification →
  verify_risk_consistency → escalation → explanation (after anomaly/feature evidence).
- Respect entity scope from the intent filters; do not broaden to dataset EDA for entity queries.
{catalog_prompt_block()}
"""


def _default_ollama_transport(settings: Settings) -> OllamaTransport:
    def transport(prompt: str, payload_extra: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": settings.ollama_model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            **payload_extra,
        }
        response = httpx.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/chat",
            json=body,
            timeout=settings.ollama_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Ollama response must be a JSON object")
        return cast(dict[str, Any], payload)

    return transport


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object in model output")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("model output JSON must be an object")
    return value


def _draft_from_ollama_response(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        content = payload.get("response")
    if not isinstance(content, str):
        raise ValueError("ollama response missing message content")
    return _extract_json_object(content)


def _build_prompt(parsed: ParsedIntent) -> str:
    filters = parsed.filters.model_dump(mode="json")
    return (
        f"intent={parsed.intent.value}\n"
        f"target_scope={parsed.target_scope.value}\n"
        f"confidence={parsed.confidence}\n"
        f"filters={json.dumps(filters, sort_keys=True)}\n"
        f"ambiguities={list(parsed.ambiguities)}\n"
        "Produce a minimal validated tool plan as JSON."
    )


def _fallback_result(
    parsed: ParsedIntent,
    *,
    settings: Settings,
    reasons: tuple[str, ...] = (),
) -> PlannerResult:
    plan = safe_template_for_intent(parsed, planner_version=f"{settings.planner_version}+fallback")
    if plan is None:
        return PlannerResult(
            plan=None,
            source="fallback_unavailable",
            rejection_reasons=reasons or ("no_safe_template",),
            used_fallback=True,
        )
    validated = validate_plan_semantics(
        plan,
        parsed=parsed,
        planner_version=plan.planner_version,
        max_steps=settings.planner_max_steps,
    )
    if not validated.ok:
        return PlannerResult(
            plan=None,
            source="fallback_invalid",
            rejection_reasons=validated.reasons,
            used_fallback=True,
        )
    return PlannerResult(
        plan=validated.plan,
        source="fallback",
        rejection_reasons=reasons,
        used_fallback=True,
    )


def plan_for_intent(
    parsed: ParsedIntent,
    *,
    settings: Settings,
    transport: OllamaTransport | None = None,
    force: bool = False,
) -> PlannerResult:
    """Propose a ValidatedPlan via Ollama (optional) with retry and safe fallback.

    When planner_enabled is false (and force is false), use deterministic fallback only.
    """
    if not settings.planner_enabled and not force:
        return _fallback_result(parsed, settings=settings)

    if not settings.ollama_enabled and not force:
        return _fallback_result(parsed, settings=settings)

    # force with ollama disabled still uses fallback unless a transport is injected.
    active_transport = transport
    if active_transport is None and settings.ollama_enabled:
        active_transport = _default_ollama_transport(settings)
    if active_transport is None:
        return _fallback_result(parsed, settings=settings)

    prompt = _build_prompt(parsed)
    last_reasons: tuple[str, ...] = ()
    for attempt in range(2):
        try:
            payload = active_transport(
                prompt
                if attempt == 0
                else prompt + "\nPrevious output was invalid. Retry JSON only.",
                {},
            )
            draft = _draft_from_ollama_response(payload)
            result: ValidationResult = validate_plan_semantics(
                draft,
                parsed=parsed,
                planner_version=settings.planner_version,
                max_steps=settings.planner_max_steps,
            )
            if result.ok and result.plan is not None:
                return PlannerResult(plan=result.plan, source="ollama", used_fallback=False)
            last_reasons = result.reasons or ("validation_failed",)
        except (ValueError, ValidationError, httpx.HTTPError, KeyError, TypeError) as exc:
            last_reasons = (f"planner_error:{exc}",)

    return _fallback_result(parsed, settings=settings, reasons=last_reasons)
