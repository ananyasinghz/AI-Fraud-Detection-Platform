"""Deterministic offline intent extractor for CI and Ollama-down paths."""

from __future__ import annotations

import re
from decimal import Decimal

from backend.app.domain.enums import IntentType, PatternType, TargetScope
from backend.app.nlu.schemas import IntentDraft

_CUSTOMER_ID = re.compile(
    r"\bcustomer\s+id\s*[#:]?\s*([A-Za-z0-9_.:-]{1,128})\b"
    r"|\bcustomer\s+([A-Za-z0-9_.:-]{1,128})\b"
    r"|\bid\s*[#:]?\s*([A-Za-z0-9_.:-]{1,128})\b",
    re.IGNORECASE,
)
_TRANSACTION_ID = re.compile(
    r"\b(?:transaction(?:\s+id)?|txn)\s*[#:]?\s*([A-Za-z0-9_.:-]{1,128})\b",
    re.IGNORECASE,
)
_INVALID_CUSTOMER_MARK = re.compile(
    r"\bcustomer(?:\s+id)?\s*[#:]?\s*([^A-Za-z0-9_.:-]+\S*)",
    re.IGNORECASE,
)
_AMOUNT_OVER = re.compile(
    r"(?:over|above|greater than|>)\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)"
    r"|(?:more than)\s*\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)"
    r"|(?:more than)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:dollars|usd)\b",
    re.IGNORECASE,
)
_AMOUNT_UNDER = re.compile(
    r"(?:under|below|less than|<)\s*\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_TXN_COUNT = re.compile(
    r"(?:more than\s+)?(\d+)\s*\+?\s*(?:transactions|txns|payments)",
    re.IGNORECASE,
)


def _money_to_decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(",", ""))


def extract_fallback(query: str) -> IntentDraft:
    """Keyword/regex extractor covering mandatory Phase 5 cases and paraphrases."""
    text = query.strip()
    lower = text.lower()
    ambiguities: list[str] = []
    customer_ids: list[str] = []
    for match in _CUSTOMER_ID.finditer(text):
        candidate = next(group for group in match.groups() if group)
        if candidate.lower() in {"id", "customer"}:
            continue
        customer_ids.append(candidate)
    transaction_ids = [match.group(1) for match in _TRANSACTION_ID.finditer(text)]
    if not customer_ids and _INVALID_CUSTOMER_MARK.search(text) and "suspicious" in lower:
        ambiguities.append("invalid_customer_id")
        return IntentDraft(
            intent=IntentType.ENTITY_INVESTIGATION,
            target_scope=TargetScope.CUSTOMER,
            confidence=0.4,
            ambiguities=ambiguities,
        )

    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    over = _AMOUNT_OVER.search(text)
    under = _AMOUNT_UNDER.search(text)
    if over:
        raw_amount = next(group for group in over.groups() if group)
        amount_min = _money_to_decimal(raw_amount)
    if under:
        amount_max = _money_to_decimal(under.group(1))

    relative_date: str | None = None
    if "last 30 days" in lower or "past 30 days" in lower or "previous 30 days" in lower:
        relative_date = "last_30_days"
    elif "this month" in lower or "suddenly increase spending this month" in lower:
        relative_date = "this_month"
    elif "last 7 days" in lower:
        relative_date = "last_7_days"

    # Mandatory / high-signal intents (order matters: specific before broad).
    if "structuring" in lower or "smurfing" in lower:
        pattern = PatternType.STRUCTURING if "structuring" in lower else PatternType.SMURFING
        return IntentDraft(
            intent=IntentType.PATTERN_SEARCH,
            target_scope=TargetScope.COHORT,
            confidence=0.86,
            pattern_type=pattern,
            relative_date=relative_date or "last_30_days",
            currency="USD",
            ambiguities=ambiguities,
        )

    txn_count_hit = "10+" in lower or "10 +" in lower or _TXN_COUNT.search(lower) is not None
    if txn_count_hit and (amount_max is not None or "under" in lower or "below" in lower):
        return IntentDraft(
            intent=IntentType.THRESHOLD_AGGREGATION,
            target_scope=TargetScope.COHORT,
            confidence=0.84,
            amount_max=amount_max or Decimal("10000"),
            currency="USD",
            relative_date=relative_date,
            ambiguities=ambiguities,
        )

    money_lookup_terms = ("transaction", "transactions", "payment", "payments")
    if amount_min is not None and any(term in lower for term in money_lookup_terms):
        return IntentDraft(
            intent=IntentType.SIMPLE_LOOKUP,
            target_scope=TargetScope.DATASET,
            confidence=0.9,
            amount_min=amount_min,
            currency="USD",
            relative_date=relative_date,
            ambiguities=ambiguities,
        )

    if customer_ids and (
        "suspicious" in lower
        or "investigate" in lower
        or re.search(r"\bis\b.+\bsuspicious\b", lower)
    ):
        return IntentDraft(
            intent=IntentType.ENTITY_INVESTIGATION,
            target_scope=TargetScope.CUSTOMER,
            confidence=0.88,
            customer_ids=customer_ids[:1],
            relative_date=relative_date,
            ambiguities=ambiguities,
        )

    if customer_ids and (
        "increase spending" in lower
        or "suddenly increase" in lower
        or "spending this month" in lower
        or "spending spike" in lower
        or "spike" in lower
        or "feature" in lower
    ):
        return IntentDraft(
            intent=IntentType.FEATURE_COMPARISON,
            target_scope=TargetScope.CUSTOMER,
            confidence=0.85,
            customer_ids=customer_ids[:1],
            relative_date=relative_date or "this_month",
            ambiguities=ambiguities,
        )

    if "score" in lower or "fraud score" in lower:
        return IntentDraft(
            intent=IntentType.TRANSACTION_SCORING,
            target_scope=TargetScope.TRANSACTION if transaction_ids else TargetScope.CUSTOMER,
            confidence=0.8 if transaction_ids else 0.55,
            customer_ids=customer_ids[:1],
            transaction_ids=transaction_ids[:1],
            ambiguities=ambiguities
            if transaction_ids
            else [*ambiguities, "missing_transaction_id"],
        )

    if "explain" in lower or "why was" in lower or "explanation" in lower:
        return IntentDraft(
            intent=IntentType.EXPLANATION_REQUEST,
            target_scope=TargetScope.CUSTOMER if customer_ids else TargetScope.DATASET,
            confidence=0.75,
            customer_ids=customer_ids[:1],
            ambiguities=ambiguities or ["explanation_needs_phase_8"],
        )

    if (
        "analyse this dataset" in lower
        or "analyze this dataset" in lower
        or "suspicious activity" in lower
        or "broad" in lower
        or "eda" in lower
    ):
        return IntentDraft(
            intent=IntentType.BROAD_EXPLORATION,
            target_scope=TargetScope.DATASET,
            confidence=0.82,
            relative_date=relative_date,
            ambiguities=ambiguities,
        )

    if customer_ids:
        return IntentDraft(
            intent=IntentType.SIMPLE_LOOKUP,
            target_scope=TargetScope.CUSTOMER,
            confidence=0.7,
            customer_ids=customer_ids[:1],
            relative_date=relative_date,
            ambiguities=ambiguities,
        )

    ambiguities.append("fallback_low_confidence")
    return IntentDraft(
        intent=IntentType.BROAD_EXPLORATION,
        target_scope=TargetScope.DATASET,
        confidence=0.35,
        ambiguities=ambiguities,
    )
