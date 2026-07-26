"""Deterministic registration and dispatch for Phase 2 rules."""

from collections.abc import Mapping
from dataclasses import dataclass

from backend.app.domain.rules import RuleResult
from backend.app.policy.config import PolicyConfig
from backend.app.rules.base import DeterministicRule, RuleInput
from backend.app.rules.implementations import (
    HighRiskCountryRule,
    ProfileDeviationRule,
    RapidCashOutRule,
    RoundNumberRule,
    SmurfingRule,
    StructuringRule,
    VelocityRule,
)


class UnknownRuleError(LookupError):
    """Raised when no exact rule registration exists."""


@dataclass(frozen=True, slots=True)
class RegisteredRule:
    rule_id: str
    implementation: DeterministicRule


class RuleEngine:
    """Dispatch supplied feature results through registered deterministic rules."""

    def __init__(self) -> None:
        self._rules: dict[str, RegisteredRule] = {}

    def register(self, implementation: DeterministicRule) -> None:
        rule_id = implementation.rule_id
        if rule_id in self._rules:
            raise ValueError(f"rule already registered: {rule_id}")
        self._rules[rule_id] = RegisteredRule(rule_id, implementation)

    def registered(self) -> tuple[str, ...]:
        return tuple(sorted(self._rules))

    def dispatch(
        self,
        rule_id: str,
        *,
        rule_input: RuleInput,
        policy: PolicyConfig,
    ) -> RuleResult:
        registration = self._rules.get(rule_id)
        if registration is None:
            raise UnknownRuleError(f"unknown rule: {rule_id}")
        return registration.implementation.evaluate(rule_input, policy)

    __call__ = dispatch

    def evaluate_many(
        self,
        *,
        rule_inputs: Mapping[str, RuleInput],
        policy: PolicyConfig,
        rule_ids: tuple[str, ...] | None = None,
    ) -> tuple[RuleResult, ...]:
        """Evaluate per-rule feature bundles in stable rule-id order."""

        selected = tuple(sorted(rule_inputs)) if rule_ids is None else tuple(sorted(rule_ids))
        if len(selected) != len(set(selected)):
            raise ValueError("rule_ids cannot contain duplicates")
        missing_inputs = tuple(rule_id for rule_id in selected if rule_id not in rule_inputs)
        if missing_inputs:
            raise ValueError(f"missing rule inputs: {', '.join(missing_inputs)}")
        return tuple(
            self.dispatch(rule_id, rule_input=rule_inputs[rule_id], policy=policy)
            for rule_id in selected
        )


def build_rule_engine() -> RuleEngine:
    engine = RuleEngine()
    for implementation in (
        StructuringRule(),
        SmurfingRule(),
        VelocityRule(),
        RapidCashOutRule(),
        RoundNumberRule(),
        ProfileDeviationRule(),
        HighRiskCountryRule(),
    ):
        engine.register(implementation)
    return engine


RULE_ENGINE = build_rule_engine()

__all__ = [
    "RULE_ENGINE",
    "RegisteredRule",
    "RuleEngine",
    "UnknownRuleError",
    "build_rule_engine",
]
