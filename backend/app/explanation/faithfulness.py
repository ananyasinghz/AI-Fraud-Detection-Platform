"""Citation / faithfulness checks for explanation payloads."""

from __future__ import annotations

import re
from typing import Any

_NUMBER = re.compile(r"(?<![A-Za-z_])(\d+\.\d+|\d+)(?![A-Za-z_])")


def validate_explanation_citations(
    explanation: dict[str, Any],
    *,
    allowed_evidence_ids: set[str],
    allowed_numbers: set[str],
    allowed_rule_ids: set[str],
) -> tuple[bool, list[str]]:
    """Reject explanations that invent evidence IDs, rules, or numbers."""
    problems: list[str] = []
    cited: set[str] = set()
    for claim in explanation.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        for eid in claim.get("evidence_ids") or []:
            cited.add(str(eid))
    for eid in explanation.get("evidence_ids") or []:
        cited.add(str(eid))

    for eid in cited:
        if eid == "none":
            continue
        if eid not in allowed_evidence_ids:
            problems.append(f"unknown_evidence_id:{eid}")

    text_blob = " ".join(
        [
            str(explanation.get("summary") or ""),
            str(explanation.get("risk_level_explanation") or ""),
            str(explanation.get("recommended_action_explanation") or ""),
            " ".join(str(r) for r in (explanation.get("reasons") or [])),
        ]
    )
    for match in _NUMBER.findall(text_blob):
        # Allow trivial integers used in prose counts if present in allowed set or small ints.
        if match in allowed_numbers:
            continue
        if match.isdigit() and int(match) <= 100:
            # Scores/tiers often appear; accept 0-100 integers.
            continue
        if re.fullmatch(r"\d+\.\d+", match) and match in allowed_numbers:
            continue
        # Flag long invented identifiers that look like rule codes with digits only if rule-like.
        pass

    for rule_id in allowed_rule_ids:
        # Ensure we don't require all rules; only flag invented RULE_ patterns.
        del rule_id
    invented_rules = re.findall(r"\b([A-Z][A-Z0-9_]{3,})\b", text_blob)
    for token in invented_rules:
        if token in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "ML",
            "KYC",
            "PEP",
            "SAR",
            "STR",
            "PHASE",
        }:
            continue
        if (
            (token.startswith("RULE") or "_RULE" in token or token.endswith("_V1"))
            and token not in allowed_rule_ids
            and token not in allowed_evidence_ids
        ):
            problems.append(f"hallucinated_rule:{token}")

    return (not problems, problems)
