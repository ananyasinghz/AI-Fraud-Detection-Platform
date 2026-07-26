"""Ollama-backed intent parser with one retry and deterministic fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Protocol, cast

import httpx
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.domain.enums import PatternType, TargetScope
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.intent import AnalysisRequest, ParsedIntent
from backend.app.nlu.date_normalizer import apply_relative_dates
from backend.app.nlu.fallback import extract_fallback
from backend.app.nlu.schemas import IntentDraft

ENTITY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")

OllamaTransport = Callable[[str, dict[str, Any]], dict[str, Any]]


class SupportsSettings(Protocol):
    ollama_enabled: bool
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: float
    intent_parser_version: str


_SYSTEM_PROMPT = """You extract fraud-investigation intent as JSON only.
Return one JSON object with keys:
intent, target_scope, confidence, customer_ids, account_ids, transaction_ids,
segment, country, transaction_type, currency, pattern_type, amount_min, amount_max,
max_results, relative_date, date_from, date_to, ambiguities.
intent must be one of: broad_exploration, simple_lookup, threshold_aggregation,
feature_comparison, pattern_search, entity_investigation, transaction_scoring,
explanation_request.
relative_date may be last_30_days, this_month, last_7_days, last_90_days, or null.
Do not compute calendar dates; leave absolute dates null unless explicitly stated as ISO-8601.
Never invent entity IDs. If unsure, lower confidence and add ambiguities.
"""


def _default_ollama_transport(
    settings: Settings,
) -> OllamaTransport:
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


def _sanitize_ids(values: list[str], *, field: str, ambiguities: list[str]) -> list[str]:
    clean: list[str] = []
    for item in values:
        candidate = item.strip()
        if not candidate:
            continue
        if not ENTITY_ID_PATTERN.fullmatch(candidate):
            ambiguities.append(f"invalid_{field}:{candidate}")
            continue
        if candidate not in clean:
            clean.append(candidate)
    return clean[:100]


def draft_to_parsed_intent(
    draft: IntentDraft,
    *,
    request: AnalysisRequest,
    parser_version: str,
) -> ParsedIntent:
    ambiguities = list(draft.ambiguities)
    customer_ids = _sanitize_ids(draft.customer_ids, field="customer_id", ambiguities=ambiguities)
    account_ids = _sanitize_ids(draft.account_ids, field="account_id", ambiguities=ambiguities)
    transaction_ids = _sanitize_ids(
        draft.transaction_ids,
        field="transaction_id",
        ambiguities=ambiguities,
    )

    date_from, date_to, date_ambiguities = apply_relative_dates(
        as_of=request.as_of,
        relative_date=draft.relative_date,
        date_from=draft.date_from,
        date_to=draft.date_to,
    )
    ambiguities.extend(date_ambiguities)

    country = draft.country.upper() if draft.country else None
    if country and not re.fullmatch(r"^[A-Z]{2}$", country):
        ambiguities.append(f"invalid_country:{draft.country}")
        country = None
    currency = draft.currency.upper() if draft.currency else None
    if currency and not re.fullmatch(r"^[A-Z]{3}$", currency):
        ambiguities.append(f"invalid_currency:{draft.currency}")
        currency = None

    pattern_type = draft.pattern_type
    if isinstance(pattern_type, str):
        try:
            pattern_type = PatternType(pattern_type)
        except ValueError:
            ambiguities.append(f"invalid_pattern_type:{pattern_type}")
            pattern_type = None

    # Merge caller-supplied filters without silently broadening empty draft scope.
    base = request.filters
    filters = NormalizedFilters(
        date_from=date_from or base.date_from,
        date_to=date_to or base.date_to,
        customer_ids=customer_ids or list(base.customer_ids),
        account_ids=account_ids or list(base.account_ids),
        transaction_ids=transaction_ids or list(base.transaction_ids),
        segment=draft.segment or base.segment,
        country=country or base.country,
        transaction_type=draft.transaction_type or base.transaction_type,
        currency=currency or base.currency,
        pattern_type=pattern_type or base.pattern_type,
        amount_min=draft.amount_min if draft.amount_min is not None else base.amount_min,
        amount_max=draft.amount_max if draft.amount_max is not None else base.amount_max,
        max_results=draft.max_results or base.max_results,
    )

    entities: dict[str, list[str]] = {}
    if customer_ids:
        entities["customer_ids"] = customer_ids
    if account_ids:
        entities["account_ids"] = account_ids
    if transaction_ids:
        entities["transaction_ids"] = transaction_ids

    scope = draft.target_scope
    if customer_ids and scope is TargetScope.DATASET:
        scope = TargetScope.CUSTOMER

    return ParsedIntent(
        intent=draft.intent,
        target_scope=scope,
        filters=filters,
        confidence=draft.confidence,
        extracted_entities=entities,
        ambiguities=ambiguities[:20],
        parser_version=parser_version,
    )


def _draft_from_ollama_response(payload: dict[str, Any]) -> IntentDraft:
    message = payload.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        # Some servers put JSON at top-level response field.
        content = payload.get("response")
    if not isinstance(content, str):
        raise ValueError("ollama response missing message content")
    data = _extract_json_object(content)
    # Coerce numeric amounts.
    for key in ("amount_min", "amount_max"):
        if key in data and data[key] is not None and not isinstance(data[key], Decimal):
            data[key] = Decimal(str(data[key]))
    return IntentDraft.model_validate(data)


def parse_intent(
    request: AnalysisRequest,
    *,
    settings: Settings,
    transport: OllamaTransport | None = None,
) -> ParsedIntent:
    """Parse NL intent via Ollama (optional) with one retry, else deterministic fallback."""
    parser_version = settings.intent_parser_version
    if not settings.ollama_enabled and transport is None:
        draft = extract_fallback(request.query)
        parsed = draft_to_parsed_intent(draft, request=request, parser_version=parser_version)
        return parsed.model_copy(
            update={"parser_version": f"{parser_version}+fallback"},
        )

    active_transport = transport or _default_ollama_transport(settings)
    prompt = f"as_of={request.as_of.isoformat()}\nquery={request.query}\nExtract intent JSON."
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            payload = active_transport(prompt, {})
            draft = _draft_from_ollama_response(payload)
            return draft_to_parsed_intent(
                draft,
                request=request,
                parser_version=parser_version,
            )
        except (ValidationError, ValueError, httpx.HTTPError, KeyError, TypeError) as exc:
            last_error = exc
            continue

    draft = extract_fallback(request.query)
    draft.ambiguities = [
        *draft.ambiguities,
        f"ollama_fallback:{type(last_error).__name__ if last_error else 'unknown'}",
    ]
    parsed = draft_to_parsed_intent(draft, request=request, parser_version=parser_version)
    return parsed.model_copy(update={"parser_version": f"{parser_version}+fallback"})
