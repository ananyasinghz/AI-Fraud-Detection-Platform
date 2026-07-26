"""Phase 2 deterministic rule implementations."""

from datetime import timedelta
from decimal import Decimal
from typing import cast

from backend.app.domain.enums import RuleSeverity, TransactionDirection, ValueType
from backend.app.domain.features import FeatureResult
from backend.app.domain.rules import RuleThreshold
from backend.app.policy.config import PolicyConfig
from backend.app.rules.base import DeterministicRule, PreparedFeatures, RequiredFeature


def _integer_threshold(name: str, value: int, unit: str) -> RuleThreshold:
    return RuleThreshold(name=name, value_type=ValueType.INTEGER, value=value, unit=unit)


def _float_threshold(name: str, value: float, unit: str) -> RuleThreshold:
    return RuleThreshold(name=name, value_type=ValueType.FLOAT, value=value, unit=unit)


def _money_threshold(name: str, value: int, policy: PolicyConfig) -> RuleThreshold:
    return _integer_threshold(name, value, f"{policy.currency}_minor")


def _integer(features: PreparedFeatures, name: str) -> int:
    return cast(int, features.values[name].value)


def _decimal(features: PreparedFeatures, name: str) -> Decimal:
    return cast(Decimal, features.values[name].value)


def _boolean(features: PreparedFeatures, name: str) -> bool:
    return cast(bool, features.values[name].value)


def _policy_currency_required(
    results: dict[str, FeatureResult],
    policy: PolicyConfig,
) -> str | None:
    for result in results.values():
        request = result.request
        if request.transaction_filter.currency != policy.currency:
            return "POLICY_CURRENCY_SCOPE_REQUIRED"
    return None


class StructuringRule(DeterministicRule):
    """Fire at equality when enough policy-bounded deposits are present."""

    rule_id = "structuring.v1"
    severity = RuleSeverity.HIGH
    required_features = (
        RequiredFeature(
            "subthreshold_count",
            "subthreshold_count",
            ValueType.INTEGER,
            minimum=0,
        ),
    )

    def thresholds(self, policy: PolicyConfig) -> tuple[RuleThreshold, ...]:
        return (
            _integer_threshold(
                "minimum_count",
                policy.structuring.minimum_count,
                "transactions",
            ),
            _money_threshold(
                "reporting_threshold_minor",
                policy.reporting_threshold_minor,
                policy,
            ),
            _float_threshold(
                "lower_bound_ratio",
                policy.structuring.lower_bound_ratio,
                "ratio",
            ),
            _float_threshold(
                "upper_bound_ratio",
                policy.structuring.upper_bound_ratio,
                "ratio",
            ),
        )

    def expected_window(self, policy: PolicyConfig) -> timedelta:
        return timedelta(days=policy.structuring.window_days)

    def validate_requests(
        self,
        results: dict[str, FeatureResult],
        policy: PolicyConfig,
    ) -> str | None:
        return _policy_currency_required(results, policy)

    def decide(self, features: PreparedFeatures, policy: PolicyConfig) -> tuple[bool, str]:
        fired = _integer(features, "subthreshold_count") >= policy.structuring.minimum_count
        return fired, (
            "MULTIPLE_SUB_THRESHOLD_CASH_DEPOSITS" if fired else "SUB_THRESHOLD_COUNT_BELOW_MINIMUM"
        )


class SmurfingRule(DeterministicRule):
    """Require matching inbound count and distinct-counterparty features."""

    rule_id = "smurfing.v1"
    severity = RuleSeverity.HIGH
    required_features = (
        RequiredFeature(
            "transaction_count",
            "transaction_count",
            ValueType.INTEGER,
            minimum=0,
        ),
        RequiredFeature(
            "distinct_counterparties",
            "distinct_counterparties",
            ValueType.INTEGER,
            minimum=0,
        ),
    )

    def thresholds(self, policy: PolicyConfig) -> tuple[RuleThreshold, ...]:
        return (
            _integer_threshold(
                "minimum_transactions",
                policy.smurfing.minimum_transactions,
                "transactions",
            ),
            _integer_threshold(
                "minimum_distinct_senders",
                policy.smurfing.minimum_distinct_senders,
                "distinct",
            ),
        )

    def expected_window(self, policy: PolicyConfig) -> timedelta:
        return timedelta(hours=policy.smurfing.window_hours)

    def validate_requests(
        self,
        results: dict[str, FeatureResult],
        policy: PolicyConfig,
    ) -> str | None:
        del policy
        for result in results.values():
            request = result.request
            if request.transaction_filter.directions != (TransactionDirection.CREDIT,):
                return "INBOUND_TRANSACTION_SCOPE_REQUIRED"
        return None

    def decide(self, features: PreparedFeatures, policy: PolicyConfig) -> tuple[bool, str]:
        count_ok = _integer(features, "transaction_count") >= policy.smurfing.minimum_transactions
        senders_ok = (
            _integer(features, "distinct_counterparties")
            >= policy.smurfing.minimum_distinct_senders
        )
        fired = count_ok and senders_ok
        return fired, ("MULTIPLE_INBOUND_SENDERS" if fired else "SMURFING_THRESHOLDS_NOT_MET")


class VelocityRule(DeterministicRule):
    """Fire when the supplied rolling count reaches the configured minimum."""

    rule_id = "velocity.v1"
    severity = RuleSeverity.MEDIUM
    required_features = (
        RequiredFeature("rolling_count", "rolling_count", ValueType.INTEGER, minimum=0),
    )

    def thresholds(self, policy: PolicyConfig) -> tuple[RuleThreshold, ...]:
        return (
            _integer_threshold(
                "minimum_transaction_count",
                policy.velocity.minimum_transaction_count,
                "transactions",
            ),
        )

    def expected_window(self, policy: PolicyConfig) -> timedelta:
        return timedelta(minutes=policy.velocity.window_minutes)

    def decide(self, features: PreparedFeatures, policy: PolicyConfig) -> tuple[bool, str]:
        fired = _integer(features, "rolling_count") >= policy.velocity.minimum_transaction_count
        return fired, ("HIGH_TRANSACTION_VELOCITY" if fired else "VELOCITY_COUNT_BELOW_MINIMUM")


class RapidCashOutRule(DeterministicRule):
    """Fire when qualifying outflows reach the configured inflow ratio."""

    rule_id = "rapid_cash_out.v1"
    severity = RuleSeverity.HIGH
    required_features = (
        RequiredFeature(
            "rapid_cash_out_ratio",
            "rapid_cash_out_ratio",
            ValueType.DECIMAL,
            minimum=Decimal(0),
        ),
    )

    def thresholds(self, policy: PolicyConfig) -> tuple[RuleThreshold, ...]:
        return (
            _money_threshold(
                "minimum_inflow_minor",
                policy.rapid_cash_out.minimum_inflow_minor,
                policy,
            ),
            _float_threshold(
                "minimum_cash_out_ratio",
                policy.rapid_cash_out.minimum_cash_out_ratio,
                "ratio",
            ),
        )

    def expected_window(self, policy: PolicyConfig) -> timedelta:
        return timedelta(minutes=policy.rapid_cash_out.window_minutes)

    def validate_requests(
        self,
        results: dict[str, FeatureResult],
        policy: PolicyConfig,
    ) -> str | None:
        return _policy_currency_required(results, policy)

    def decide(self, features: PreparedFeatures, policy: PolicyConfig) -> tuple[bool, str]:
        minimum = Decimal(str(policy.rapid_cash_out.minimum_cash_out_ratio))
        fired = _decimal(features, "rapid_cash_out_ratio") >= minimum
        return fired, ("RAPID_CASH_OUT_RATIO_MET" if fired else "CASH_OUT_RATIO_BELOW_MINIMUM")


class RoundNumberRule(DeterministicRule):
    """Require both sample-size and round-number-ratio thresholds."""

    rule_id = "round_numbers.v1"
    severity = RuleSeverity.MEDIUM
    required_features = (
        RequiredFeature(
            "transaction_count",
            "transaction_count",
            ValueType.INTEGER,
            minimum=0,
        ),
        RequiredFeature(
            "round_number_ratio",
            "round_number_ratio",
            ValueType.DECIMAL,
            minimum=Decimal(0),
            maximum=Decimal(1),
        ),
    )

    def thresholds(self, policy: PolicyConfig) -> tuple[RuleThreshold, ...]:
        return (
            _integer_threshold(
                "minimum_transaction_count",
                policy.round_numbers.minimum_transaction_count,
                "transactions",
            ),
            _float_threshold(
                "minimum_round_number_ratio",
                policy.round_numbers.minimum_round_number_ratio,
                "ratio",
            ),
            _money_threshold(
                "rounding_increment_minor",
                policy.round_numbers.rounding_increment_minor,
                policy,
            ),
        )

    def expected_window(self, policy: PolicyConfig) -> timedelta:
        return timedelta(days=policy.round_numbers.window_days)

    def validate_requests(
        self,
        results: dict[str, FeatureResult],
        policy: PolicyConfig,
    ) -> str | None:
        return _policy_currency_required(results, policy)

    def decide(self, features: PreparedFeatures, policy: PolicyConfig) -> tuple[bool, str]:
        count_ok = (
            _integer(features, "transaction_count")
            >= policy.round_numbers.minimum_transaction_count
        )
        ratio_ok = _decimal(features, "round_number_ratio") >= Decimal(
            str(policy.round_numbers.minimum_round_number_ratio)
        )
        fired = count_ok and ratio_ok
        return fired, ("HIGH_ROUND_NUMBER_ACTIVITY" if fired else "ROUND_NUMBER_THRESHOLDS_NOT_MET")


class ProfileDeviationRule(DeterministicRule):
    """Fire only for sufficient, material observed-versus-expected mismatch."""

    rule_id = "profile_deviation.v1"
    severity = RuleSeverity.HIGH
    required_features = (
        RequiredFeature("data_sufficiency", "data_sufficiency", ValueType.BOOLEAN),
        RequiredFeature(
            "transaction_count",
            "transaction_count",
            ValueType.INTEGER,
            minimum=0,
        ),
        RequiredFeature(
            "transaction_total",
            "transaction_total",
            ValueType.DECIMAL,
            minimum=Decimal(0),
        ),
        RequiredFeature(
            "activity_vs_expected",
            "activity_vs_expected",
            ValueType.DECIMAL,
            minimum=Decimal(0),
        ),
    )

    def thresholds(self, policy: PolicyConfig) -> tuple[RuleThreshold, ...]:
        return (
            _integer_threshold(
                "minimum_transaction_count",
                policy.profile_deviation.minimum_transaction_count,
                "transactions",
            ),
            _money_threshold(
                "minimum_observed_volume_minor",
                policy.profile_deviation.minimum_observed_volume_minor,
                policy,
            ),
            _float_threshold(
                "minimum_expected_volume_ratio",
                policy.profile_deviation.minimum_expected_volume_ratio,
                "ratio",
            ),
        )

    def expected_window(self, policy: PolicyConfig) -> timedelta:
        return timedelta(days=policy.profile_deviation.window_days)

    def validate_requests(
        self,
        results: dict[str, FeatureResult],
        policy: PolicyConfig,
    ) -> str | None:
        return _policy_currency_required(results, policy)

    def decide(self, features: PreparedFeatures, policy: PolicyConfig) -> tuple[bool, str]:
        if not _boolean(features, "data_sufficiency"):
            return False, "INSUFFICIENT_PROFILE_DATA"
        count_ok = (
            _integer(features, "transaction_count")
            >= policy.profile_deviation.minimum_transaction_count
        )
        volume_ok = _decimal(features, "transaction_total") >= Decimal(
            policy.profile_deviation.minimum_observed_volume_minor
        )
        mismatch_ok = _decimal(features, "activity_vs_expected") >= Decimal(
            str(policy.profile_deviation.minimum_expected_volume_ratio)
        )
        fired = count_ok and volume_ok and mismatch_ok
        return fired, (
            "OBSERVED_ACTIVITY_EXCEEDS_PROFILE" if fired else "PROFILE_DEVIATION_THRESHOLDS_NOT_MET"
        )


class HighRiskCountryRule(DeterministicRule):
    """Require explicitly high-risk-country-scoped count and total features."""

    rule_id = "high_risk_country.v1"
    severity = RuleSeverity.HIGH
    required_features = (
        RequiredFeature(
            "transaction_count",
            "transaction_count",
            ValueType.INTEGER,
            minimum=0,
        ),
        RequiredFeature(
            "transaction_total",
            "transaction_total",
            ValueType.DECIMAL,
            minimum=Decimal(0),
        ),
    )

    def thresholds(self, policy: PolicyConfig) -> tuple[RuleThreshold, ...]:
        return (
            _integer_threshold(
                "minimum_transaction_count",
                policy.high_risk_country.minimum_transaction_count,
                "transactions",
            ),
            _money_threshold(
                "minimum_total_minor",
                policy.high_risk_country.minimum_total_minor,
                policy,
            ),
        )

    def expected_window(self, policy: PolicyConfig) -> timedelta:
        return timedelta(days=policy.high_risk_country.window_days)

    def validate_requests(
        self,
        results: dict[str, FeatureResult],
        policy: PolicyConfig,
    ) -> str | None:
        currency_reason = _policy_currency_required(results, policy)
        if currency_reason is not None:
            return currency_reason
        allowed = set(policy.high_risk_countries)
        for result in results.values():
            request = result.request
            countries = set(request.transaction_filter.countries)
            if not countries or not countries.issubset(allowed):
                return "HIGH_RISK_COUNTRY_SCOPE_REQUIRED"
        return None

    def decide(self, features: PreparedFeatures, policy: PolicyConfig) -> tuple[bool, str]:
        count_ok = (
            _integer(features, "transaction_count")
            >= policy.high_risk_country.minimum_transaction_count
        )
        total_ok = _decimal(features, "transaction_total") >= Decimal(
            policy.high_risk_country.minimum_total_minor
        )
        fired = count_ok and total_ok
        return fired, (
            "HIGH_RISK_COUNTRY_ACTIVITY" if fired else "HIGH_RISK_COUNTRY_THRESHOLDS_NOT_MET"
        )


__all__ = [
    "HighRiskCountryRule",
    "ProfileDeviationRule",
    "RapidCashOutRule",
    "RoundNumberRule",
    "SmurfingRule",
    "StructuringRule",
    "VelocityRule",
]
