"""Database-independent contracts and validation for deterministic rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import ClassVar

from backend.app.domain.enums import EntityType, RuleSeverity, ValueType
from backend.app.domain.features import FeatureRequest, FeatureResult, FeatureValue
from backend.app.domain.rules import RuleResult, RuleThreshold
from backend.app.policy.config import PolicyConfig


@dataclass(frozen=True, slots=True)
class RequiredFeature:
    """One exact feature operation/value pair consumed by a rule."""

    operation: str
    value_name: str
    value_type: ValueType
    version: str = "v1"
    minimum: int | Decimal | None = None
    maximum: int | Decimal | None = None


@dataclass(frozen=True, slots=True)
class RuleInput:
    """The complete, deliberately profile-free input available to rules."""

    entity_type: EntityType
    entity_id: str
    feature_results: tuple[FeatureResult, ...]


@dataclass(frozen=True, slots=True)
class PreparedFeatures:
    values: dict[str, FeatureValue]
    used: tuple[FeatureValue, ...]
    evidence_refs: tuple[str, ...]
    results: dict[str, FeatureResult]


class DeterministicRule(ABC):
    """Thin policy comparison over supplied, query-scoped feature results."""

    rule_id: ClassVar[str]
    version: ClassVar[str] = "v1"
    severity: ClassVar[RuleSeverity]
    required_features: ClassVar[tuple[RequiredFeature, ...]]

    @abstractmethod
    def thresholds(self, policy: PolicyConfig) -> tuple[RuleThreshold, ...]:
        """Return every policy value used by this rule."""

    @abstractmethod
    def expected_window(self, policy: PolicyConfig) -> timedelta:
        """Return the exact feature window this rule accepts."""

    @abstractmethod
    def decide(self, features: PreparedFeatures, policy: PolicyConfig) -> tuple[bool, str]:
        """Apply policy to already validated feature values."""

    def validate_requests(
        self,
        results: dict[str, FeatureResult],
        policy: PolicyConfig,
    ) -> str | None:
        """Perform rule-specific request-scope checks."""

        del results, policy
        return None

    def evaluate(self, rule_input: RuleInput, policy: PolicyConfig) -> RuleResult:
        """Validate provenance and evaluate without querying or aggregating data."""

        thresholds = self.thresholds(policy)
        prepared, reason = self._prepare(rule_input, policy)
        if prepared is None:
            return self._result(
                rule_input,
                fired=False,
                reason_code=reason,
                features_used=(),
                thresholds=thresholds,
                evidence_refs=(),
            )
        if reason:
            return self._result(
                rule_input,
                fired=False,
                reason_code=reason,
                features_used=prepared.used,
                thresholds=thresholds,
                evidence_refs=prepared.evidence_refs,
            )
        fired, reason_code = self.decide(prepared, policy)
        return self._result(
            rule_input,
            fired=fired,
            reason_code=reason_code,
            features_used=prepared.used,
            thresholds=thresholds,
            evidence_refs=prepared.evidence_refs,
        )

    def _prepare(
        self,
        rule_input: RuleInput,
        policy: PolicyConfig,
    ) -> tuple[PreparedFeatures | None, str]:
        required_operations = {item.operation for item in self.required_features}
        by_operation: dict[str, FeatureResult] = {}
        for result in rule_input.feature_results:
            operation = result.request.operation
            if operation not in required_operations:
                continue
            if operation in by_operation:
                return None, "DUPLICATE_FEATURE_RESULT"
            by_operation[operation] = result

        if not required_operations.issubset(by_operation):
            return None, "MISSING_REQUIRED_FEATURES"

        selected = {name: by_operation[name] for name in required_operations}
        requests = tuple(selected[item.operation].request for item in self.required_features)
        if any(result.provenance.policy_version != policy.version for result in selected.values()):
            return None, "FEATURE_POLICY_MISMATCH"
        if any(
            request.version != requirement.version
            for request, requirement in zip(requests, self.required_features, strict=True)
        ):
            return None, "UNSUPPORTED_FEATURE_VERSION"
        if any(not self._matches_entity(request, rule_input) for request in requests):
            return None, "FEATURE_SCOPE_MISMATCH"
        expected_window = self.expected_window(policy)
        if any(
            request.window.end_exclusive - request.window.start_inclusive != expected_window
            for request in requests
        ):
            return None, "FEATURE_WINDOW_MISMATCH"
        first_signature = self._request_signature(requests[0])
        if any(self._request_signature(request) != first_signature for request in requests[1:]):
            return None, "FEATURE_SCOPE_MISMATCH"

        request_reason = self.validate_requests(selected, policy)
        if request_reason is not None:
            return None, request_reason

        values: dict[str, FeatureValue] = {}
        used: list[FeatureValue] = []
        evidence: list[str] = []
        for requirement in self.required_features:
            result = selected[requirement.operation]
            value = next(
                (item for item in result.values if item.name == requirement.value_name),
                None,
            )
            if value is None:
                return None, "MISSING_REQUIRED_FEATURE_VALUE"
            if value.value_type is not requirement.value_type or value.value is None:
                return None, "INVALID_FEATURE_VALUE"
            if isinstance(value.value, (int, Decimal)) and not isinstance(value.value, bool):
                if requirement.minimum is not None and value.value < requirement.minimum:
                    return None, "INVALID_FEATURE_VALUE"
                if requirement.maximum is not None and value.value > requirement.maximum:
                    return None, "INVALID_FEATURE_VALUE"
            values[requirement.value_name] = value
            used.append(value)
            query_id = result.provenance.query_id
            if query_id is None:
                return None, "MISSING_FEATURE_PROVENANCE"
            if query_id not in evidence:
                evidence.append(query_id)

        prepared = PreparedFeatures(
            values=values,
            used=tuple(used),
            evidence_refs=tuple(evidence),
            results=selected,
        )
        warning_codes = {
            warning.code for result in selected.values() for warning in result.warnings
        }
        if warning_codes & {
            "EMPTY_SCOPE",
            "INSUFFICIENT_BASELINE",
            "INSUFFICIENT_DATA",
            "NO_DATA",
            "NO_QUALIFYING_INFLOW",
            "NO_MATCHED_CASH_OUT",
            "ZERO_DENOMINATOR",
        }:
            return prepared, "INSUFFICIENT_FEATURE_DATA"
        if warning_codes:
            return prepared, "FEATURE_DATA_WARNINGS"

        return prepared, ""

    @staticmethod
    def _matches_entity(request: FeatureRequest, rule_input: RuleInput) -> bool:
        return request.scope.entity_type is rule_input.entity_type and request.scope.entity_ids == (
            rule_input.entity_id,
        )

    @staticmethod
    def _request_signature(request: FeatureRequest) -> tuple[object, ...]:
        return (
            request.as_of,
            request.window,
            request.scope,
            request.transaction_filter,
            request.group_by,
        )

    def _result(
        self,
        rule_input: RuleInput,
        *,
        fired: bool,
        reason_code: str,
        features_used: tuple[FeatureValue, ...],
        thresholds: tuple[RuleThreshold, ...],
        evidence_refs: tuple[str, ...],
    ) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            version=self.version,
            fired=fired,
            severity=self.severity,
            entity_type=rule_input.entity_type,
            entity_id=rule_input.entity_id,
            features_used=features_used,
            thresholds_used=thresholds,
            evidence_refs=evidence_refs,
            reason_code=reason_code,
        )


__all__ = [
    "DeterministicRule",
    "PreparedFeatures",
    "RequiredFeature",
    "RuleInput",
]
