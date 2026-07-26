"""Deterministic AML scenario generation without runtime labels."""

import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from backend.app.generation.config import (
    GenerationConfig,
    PolicyConfig,
    load_generation_config,
    load_policy_config,
)
from backend.app.generation.contracts import (
    AccountSeed,
    CounterpartySeed,
    CustomerProfileSeed,
    CustomerSeed,
    DeviceSeed,
    GenerationResult,
    RuntimeBundle,
    ScenarioAnnotation,
    ScenarioType,
    TransactionSeed,
)


class _ScenarioBuilder:
    def __init__(
        self,
        *,
        seed: int,
        split: str,
        config: GenerationConfig,
        policy: PolicyConfig,
    ) -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        self.split = split
        self.config = config
        self.policy = policy
        self.customers: list[CustomerSeed] = []
        self.profiles: list[CustomerProfileSeed] = []
        self.accounts: list[AccountSeed] = []
        self.counterparties: list[CounterpartySeed] = []
        self.devices: list[DeviceSeed] = []
        self.transactions: list[TransactionSeed] = []
        self.annotations: list[ScenarioAnnotation] = []
        self._transaction_number = 0
        self._counterparty_ids: set[str] = set()

    @property
    def as_of(self) -> datetime:
        return self.config.as_of

    def add_customer(
        self,
        key: str,
        *,
        opened_days_ago: int = 730,
        expected_min_minor: int = 50_000,
        expected_max_minor: int = 500_000,
        residence_country: str = "US",
        kyc_risk_rating: Literal["low", "medium", "high"] = "low",
        split_profile: bool = False,
    ) -> tuple[str, str, str]:
        prefix = f"{self.split}-{self.seed}-{key}"
        customer_id = f"cus-{prefix}"
        account_id = f"acc-{prefix}"
        device_id = f"dev-{prefix}"
        opened_at = self.as_of - timedelta(days=opened_days_ago)
        self.customers.append(CustomerSeed(customer_id=customer_id, created_at=opened_at))
        profile_start = opened_at
        if split_profile:
            change_at = self.as_of - timedelta(days=180)
            self.profiles.append(
                CustomerProfileSeed(
                    customer_id=customer_id,
                    segment="retail",
                    residence_country=residence_country,
                    occupation_or_industry="Professional services",
                    declared_annual_income_minor=6_000_000,
                    income_currency="USD",
                    expected_monthly_volume_min_minor=30_000,
                    expected_monthly_volume_max_minor=300_000,
                    volume_currency="USD",
                    kyc_risk_rating="low",
                    profile_effective_from=profile_start,
                    profile_effective_to=change_at,
                )
            )
            profile_start = change_at
        self.profiles.append(
            CustomerProfileSeed(
                customer_id=customer_id,
                segment="retail",
                residence_country=residence_country,
                occupation_or_industry="Professional services",
                declared_annual_income_minor=8_000_000,
                income_currency="USD",
                expected_monthly_volume_min_minor=expected_min_minor,
                expected_monthly_volume_max_minor=expected_max_minor,
                volume_currency="USD",
                kyc_risk_rating=kyc_risk_rating,
                profile_effective_from=profile_start,
            )
        )
        self.accounts.append(
            AccountSeed(
                account_id=account_id,
                customer_id=customer_id,
                account_type="checking",
                currency="USD",
                country="US",
                opened_at=opened_at,
            )
        )
        self.devices.append(
            DeviceSeed(
                device_id=device_id,
                device_type="mobile",
                first_seen_at=opened_at,
                last_seen_at=self.as_of,
            )
        )
        return customer_id, account_id, device_id

    def add_counterparty(self, key: str, *, country: str = "US") -> str:
        counterparty_id = f"cp-{self.split}-{self.seed}-{key}"
        if counterparty_id not in self._counterparty_ids:
            self._counterparty_ids.add(counterparty_id)
            self.counterparties.append(
                CounterpartySeed(
                    counterparty_id=counterparty_id,
                    display_name=f"Synthetic Counterparty {key}",
                    country=country,
                    kind="merchant_or_bank",
                )
            )
        return counterparty_id

    def add_transaction(
        self,
        *,
        customer_id: str,
        account_id: str,
        occurred_at: datetime,
        amount_minor: int,
        direction: str,
        transaction_type: str,
        channel: str,
        device_id: str | None = None,
        country: str = "US",
        counterparty_id: str | None = None,
        counterparty_account_id: str | None = None,
    ) -> None:
        self._transaction_number += 1
        transaction_id = f"txn-{self.split}-{self.seed}-{self._transaction_number:06d}"
        resolved_cp_account = counterparty_account_id
        if resolved_cp_account is None and counterparty_id is not None:
            resolved_cp_account = f"ext-{counterparty_id}"
        self.transactions.append(
            TransactionSeed.model_validate(
                {
                    "transaction_id": transaction_id,
                    "account_id": account_id,
                    "customer_id": customer_id,
                    "occurred_at": occurred_at,
                    "posted_at": occurred_at + timedelta(hours=1),
                    "amount_minor": amount_minor,
                    "currency": "USD",
                    "direction": direction,
                    "transaction_type": transaction_type,
                    "channel": channel,
                    "country": country,
                    "counterparty_id": counterparty_id,
                    "counterparty_account_id": resolved_cp_account,
                    "device_id": device_id,
                }
            )
        )

    def add_prior_clean_history(
        self,
        customer_id: str,
        account_id: str,
        device_id: str,
        *,
        count: int = 6,
    ) -> None:
        merchant = self.add_counterparty(f"merchant-{customer_id}")
        for index in range(count):
            self.add_transaction(
                customer_id=customer_id,
                account_id=account_id,
                occurred_at=self.as_of - timedelta(days=90 - index * 10),
                amount_minor=2_000 + index * 700,
                direction="debit",
                transaction_type="card_purchase",
                channel="pos",
                device_id=device_id,
                counterparty_id=merchant,
            )

    def annotate(
        self,
        *,
        key: str,
        pattern: ScenarioType,
        customer_id: str,
        window_from: datetime,
        window_to: datetime,
        expected_signals: list[str],
        notes: str,
    ) -> None:
        self.annotations.append(
            ScenarioAnnotation(
                scenario_id=f"scenario-{self.split}-{self.seed}-{key}",
                pattern_type=pattern,
                entity_type="customer",
                entity_id=customer_id,
                window_from=window_from,
                window_to=window_to,
                expected_signals=expected_signals,
                notes=notes,
            )
        )


def _generate_clean_controls(builder: _ScenarioBuilder) -> None:
    patterns = builder.config.patterns
    for index in range(builder.config.baseline_customer_count):
        customer_id, account_id, device_id = builder.add_customer(
            f"clean-{index:03d}",
            split_profile=index == 0,
        )
        merchant = builder.add_counterparty(f"clean-merchant-{index:03d}")
        for transaction_index in range(builder.config.baseline_transactions_per_customer):
            occurred_at = builder.as_of - timedelta(
                days=120 - transaction_index * 4,
                hours=index % 12,
            )
            builder.add_transaction(
                customer_id=customer_id,
                account_id=account_id,
                occurred_at=occurred_at,
                amount_minor=builder.rng.randint(1_000, 25_000),
                direction="debit",
                transaction_type="card_purchase",
                channel="pos",
                device_id=device_id,
                counterparty_id=merchant,
            )
        pattern = patterns[index % len(patterns)]
        builder.annotate(
            key=f"clean-{index:03d}",
            pattern="clean_control",
            customer_id=customer_id,
            window_from=builder.as_of - timedelta(days=120),
            window_to=builder.as_of,
            expected_signals=["no_injected_pattern", f"control_for_{pattern}"],
            notes=f"Clean control paired with the {pattern} scenario family.",
        )


def _generate_structuring(builder: _ScenarioBuilder, index: int) -> None:
    key = f"structuring-{index:02d}"
    customer_id, account_id, device_id = builder.add_customer(key)
    builder.add_prior_clean_history(customer_id, account_id, device_id)
    start = builder.as_of - timedelta(days=7)
    for offset in range(builder.policy.structuring.minimum_count + 2):
        amount = int(
            builder.policy.reporting_threshold_minor
            * builder.rng.uniform(
                builder.policy.structuring.lower_bound_ratio,
                builder.policy.structuring.upper_bound_ratio,
            )
        )
        builder.add_transaction(
            customer_id=customer_id,
            account_id=account_id,
            occurred_at=start + timedelta(days=offset),
            amount_minor=amount,
            direction="credit",
            transaction_type="cash_deposit",
            channel="branch",
        )
    builder.annotate(
        key=key,
        pattern="structuring",
        customer_id=customer_id,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["repeated_below_threshold_cash_deposits"],
        notes="Illustrative amounts below the configured reporting threshold.",
    )


def _generate_smurfing(builder: _ScenarioBuilder, index: int) -> None:
    key = f"smurfing-{index:02d}"
    customer_id, account_id, device_id = builder.add_customer(key)
    builder.add_prior_clean_history(customer_id, account_id, device_id)
    start = builder.as_of - timedelta(days=2)
    for offset in range(6):
        counterparty_id = builder.add_counterparty(f"{key}-sender-{offset}")
        builder.add_transaction(
            customer_id=customer_id,
            account_id=account_id,
            occurred_at=start + timedelta(hours=offset * 5),
            amount_minor=200_000 + offset * 15_000,
            direction="credit",
            transaction_type="wire_transfer",
            channel="online",
            device_id=device_id,
            counterparty_id=counterparty_id,
        )
    builder.annotate(
        key=key,
        pattern="smurfing",
        customer_id=customer_id,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["many_distinct_senders", "beneficiary_concentration"],
        notes="Multiple synthetic senders fund one beneficiary in a short window.",
    )


def _generate_velocity(builder: _ScenarioBuilder, index: int) -> None:
    key = f"velocity-{index:02d}"
    customer_id, account_id, device_id = builder.add_customer(key)
    builder.add_prior_clean_history(customer_id, account_id, device_id)
    start = builder.as_of - timedelta(hours=2)
    merchant = builder.add_counterparty(f"{key}-merchant")
    for offset in range(12):
        builder.add_transaction(
            customer_id=customer_id,
            account_id=account_id,
            occurred_at=start + timedelta(minutes=offset * 4),
            amount_minor=20_000 + offset * 1_000,
            direction="debit",
            transaction_type="card_purchase",
            channel="ecommerce",
            device_id=device_id,
            counterparty_id=merchant,
        )
    builder.annotate(
        key=key,
        pattern="velocity",
        customer_id=customer_id,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["high_transaction_count_short_window"],
        notes="Synthetic burst of card activity.",
    )


def _generate_rapid_cash_out(builder: _ScenarioBuilder, index: int) -> None:
    key = f"rapid-cash-out-{index:02d}"
    customer_id, account_id, device_id = builder.add_customer(key)
    builder.add_prior_clean_history(customer_id, account_id, device_id)
    # Keep both legs inside the policy rapid_cash_out window (default 120 minutes).
    start = builder.as_of - timedelta(minutes=90)
    recipient = builder.add_counterparty(f"{key}-recipient")
    builder.add_transaction(
        customer_id=customer_id,
        account_id=account_id,
        occurred_at=start,
        amount_minor=900_000,
        direction="credit",
        transaction_type="cash_deposit",
        channel="branch",
    )
    builder.add_transaction(
        customer_id=customer_id,
        account_id=account_id,
        occurred_at=start + timedelta(minutes=30),
        amount_minor=850_000,
        direction="debit",
        transaction_type="wire_transfer",
        channel="online",
        device_id=device_id,
        counterparty_id=recipient,
    )
    builder.annotate(
        key=key,
        pattern="rapid_cash_out",
        customer_id=customer_id,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["large_credit_followed_by_rapid_debit"],
        notes="Synthetic pass-through sequence within the rapid_cash_out policy window.",
    )


def _generate_round_number(builder: _ScenarioBuilder, index: int) -> None:
    key = f"round-number-{index:02d}"
    customer_id, account_id, device_id = builder.add_customer(key)
    builder.add_prior_clean_history(customer_id, account_id, device_id)
    start = builder.as_of - timedelta(days=30)
    sender = builder.add_counterparty(f"{key}-sender")
    for offset in range(10):
        builder.add_transaction(
            customer_id=customer_id,
            account_id=account_id,
            occurred_at=start + timedelta(days=offset * 2),
            amount_minor=100_000 if offset % 2 == 0 else 200_000,
            direction="credit",
            transaction_type="wire_transfer",
            channel="online",
            device_id=device_id,
            counterparty_id=sender,
        )
    builder.annotate(
        key=key,
        pattern="round_number",
        customer_id=customer_id,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["round_number_concentration"],
        notes="Synthetic concentration on exact whole-thousand USD amounts.",
    )


def _generate_spending_increase(builder: _ScenarioBuilder, index: int) -> None:
    key = f"spending-increase-{index:02d}"
    customer_id, account_id, device_id = builder.add_customer(key)
    merchant = builder.add_counterparty(f"{key}-merchant")
    start = builder.as_of - timedelta(days=120)
    for offset in range(9):
        amount = 6_000 if offset < 6 else 180_000
        builder.add_transaction(
            customer_id=customer_id,
            account_id=account_id,
            occurred_at=start + timedelta(days=offset * 14),
            amount_minor=amount,
            direction="debit",
            transaction_type="card_purchase",
            channel="ecommerce",
            device_id=device_id,
            counterparty_id=merchant,
        )
    builder.annotate(
        key=key,
        pattern="spending_increase",
        customer_id=customer_id,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["recent_spend_above_historical_baseline"],
        notes="Recent synthetic spend is much larger than prior history.",
    )


def _generate_profile_deviation(builder: _ScenarioBuilder, index: int) -> None:
    key = f"profile-deviation-{index:02d}"
    customer_id, account_id, device_id = builder.add_customer(
        key,
        expected_min_minor=20_000,
        expected_max_minor=100_000,
    )
    builder.add_prior_clean_history(customer_id, account_id, device_id)
    start = builder.as_of - timedelta(days=20)
    sender = builder.add_counterparty(f"{key}-sender")
    for offset in range(5):
        builder.add_transaction(
            customer_id=customer_id,
            account_id=account_id,
            occurred_at=start + timedelta(days=offset * 4),
            amount_minor=500_000,
            direction="credit",
            transaction_type="wire_transfer",
            channel="online",
            device_id=device_id,
            counterparty_id=sender,
        )
    builder.annotate(
        key=key,
        pattern="profile_deviation",
        customer_id=customer_id,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["activity_above_declared_profile"],
        notes="Synthetic monthly volume exceeds the declared expected range.",
    )


def _generate_new_account(builder: _ScenarioBuilder, index: int) -> None:
    key = f"new-account-{index:02d}"
    customer_id, account_id, device_id = builder.add_customer(key, opened_days_ago=3)
    start = builder.as_of - timedelta(days=2)
    recipient = builder.add_counterparty(f"{key}-recipient")
    for offset in range(4):
        builder.add_transaction(
            customer_id=customer_id,
            account_id=account_id,
            occurred_at=start + timedelta(hours=offset * 8),
            amount_minor=300_000,
            direction="debit",
            transaction_type="wire_transfer",
            channel="online",
            device_id=device_id,
            counterparty_id=recipient,
        )
    builder.annotate(
        key=key,
        pattern="new_account",
        customer_id=customer_id,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["high_activity_on_new_account"],
        notes="Synthetic transfer activity immediately after account opening.",
    )


def _generate_high_risk_country(builder: _ScenarioBuilder, index: int) -> None:
    key = f"high-risk-country-{index:02d}"
    customer_id, account_id, device_id = builder.add_customer(key)
    builder.add_prior_clean_history(customer_id, account_id, device_id)
    country = builder.policy.high_risk_countries[0]
    start = builder.as_of - timedelta(days=12)
    recipient = builder.add_counterparty(f"{key}-recipient", country=country)
    for offset in range(4):
        builder.add_transaction(
            customer_id=customer_id,
            account_id=account_id,
            occurred_at=start + timedelta(days=offset * 3),
            amount_minor=250_000,
            direction="debit",
            transaction_type="wire_transfer",
            channel="online",
            device_id=device_id,
            country=country,
            counterparty_id=recipient,
        )
    builder.annotate(
        key=key,
        pattern="high_risk_country",
        customer_id=customer_id,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["configured_country_context"],
        notes="Uses fictional country code ZZ for synthetic policy testing.",
    )


def _generate_graph_relationships(builder: _ScenarioBuilder) -> None:
    """Deliberate shared-device, circular transfer, and two-hop gold relationships."""
    shared_device_id = f"dev-graph-shared-{builder.split}-{builder.seed}"
    builder.devices.append(
        DeviceSeed.model_validate(
            {
                "device_id": shared_device_id,
                "device_type": "mobile",
                "first_seen_at": builder.as_of - timedelta(days=60),
                "last_seen_at": builder.as_of - timedelta(days=1),
            }
        )
    )
    cust_a, acct_a, _ = builder.add_customer("graph-share-a")
    cust_b, acct_b, _ = builder.add_customer("graph-share-b")
    # Override per-customer devices by using the shared device on transactions only.
    start = builder.as_of - timedelta(days=5)
    builder.add_transaction(
        customer_id=cust_a,
        account_id=acct_a,
        occurred_at=start,
        amount_minor=12_000,
        direction="debit",
        transaction_type="card_purchase",
        channel="mobile",
        device_id=shared_device_id,
    )
    builder.add_transaction(
        customer_id=cust_b,
        account_id=acct_b,
        occurred_at=start + timedelta(hours=3),
        amount_minor=9_500,
        direction="debit",
        transaction_type="card_purchase",
        channel="mobile",
        device_id=shared_device_id,
    )
    builder.annotate(
        key="graph-shared-device",
        pattern="graph_relationship",
        customer_id=cust_a,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["shared_device", shared_device_id, cust_b],
        notes="Two customers deliberately share one device for Phase 7 graph gold.",
    )

    cust_c, acct_c, device_c = builder.add_customer("graph-cycle-a")
    cust_d, acct_d, device_d = builder.add_customer("graph-cycle-b")
    builder.add_transaction(
        customer_id=cust_c,
        account_id=acct_c,
        occurred_at=start + timedelta(days=1),
        amount_minor=50_000,
        direction="debit",
        transaction_type="wire_transfer",
        channel="online",
        device_id=device_c,
        counterparty_account_id=acct_d,
    )
    builder.add_transaction(
        customer_id=cust_d,
        account_id=acct_d,
        occurred_at=start + timedelta(days=1, hours=2),
        amount_minor=48_000,
        direction="debit",
        transaction_type="wire_transfer",
        channel="online",
        device_id=device_d,
        counterparty_account_id=acct_c,
    )
    builder.annotate(
        key="graph-circular",
        pattern="graph_relationship",
        customer_id=cust_c,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["circular_transfers", acct_c, acct_d],
        notes="Accounts deliberately transfer to each other for cycle detection.",
    )

    cust_e, acct_e, device_e = builder.add_customer("graph-hop-a")
    cust_f, acct_f, device_f = builder.add_customer("graph-hop-b")
    hop_cp = builder.add_counterparty("graph-hop-cp")
    builder.add_transaction(
        customer_id=cust_e,
        account_id=acct_e,
        occurred_at=start + timedelta(days=2),
        amount_minor=22_000,
        direction="debit",
        transaction_type="wire_transfer",
        channel="online",
        device_id=device_e,
        counterparty_id=hop_cp,
        counterparty_account_id=acct_f,
    )
    builder.add_transaction(
        customer_id=cust_f,
        account_id=acct_f,
        occurred_at=start + timedelta(days=2, hours=4),
        amount_minor=11_000,
        direction="debit",
        transaction_type="card_purchase",
        channel="pos",
        device_id=device_f,
        counterparty_id=hop_cp,
    )
    builder.annotate(
        key="graph-two-hop",
        pattern="graph_relationship",
        customer_id=cust_e,
        window_from=start,
        window_to=builder.as_of,
        expected_signals=["two_hop_exposure", acct_f, hop_cp],
        notes="Seed account reaches another account and counterparty within two hops.",
    )


_GENERATORS = {
    "structuring": _generate_structuring,
    "smurfing": _generate_smurfing,
    "velocity": _generate_velocity,
    "rapid_cash_out": _generate_rapid_cash_out,
    "round_number": _generate_round_number,
    "spending_increase": _generate_spending_increase,
    "profile_deviation": _generate_profile_deviation,
    "new_account": _generate_new_account,
    "high_risk_country": _generate_high_risk_country,
}


def _fingerprint(bundle: RuntimeBundle) -> str:
    payload = bundle.model_dump(mode="json", exclude={"fingerprint"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def generate_scenarios(
    *,
    seed: int,
    split: Literal["dev", "held_out", "ci_tiny"],
    generation_config_path: Path,
    policy_config_path: Path,
) -> GenerationResult:
    """Generate runtime entities and a separate offline annotation collection."""
    if split not in {"dev", "held_out", "ci_tiny"}:
        raise ValueError("split must be dev, held_out, or ci_tiny")
    config = load_generation_config(generation_config_path)
    policy = load_policy_config(policy_config_path)
    if config.currency != policy.currency:
        raise ValueError("generation and policy currency must match")
    builder = _ScenarioBuilder(
        seed=seed,
        split=split,
        config=config,
        policy=policy,
    )
    _generate_clean_controls(builder)
    for pattern in config.patterns:
        generator = _GENERATORS.get(pattern)
        if generator is None:
            raise ValueError(f"unsupported scenario pattern: {pattern}")
        for index in range(config.scenarios_per_pattern):
            generator(builder, index)
    _generate_graph_relationships(builder)

    run_id = f"aml-{config.generator_version}-{split}-{seed}"
    bundle = RuntimeBundle(
        run_id=run_id,
        seed=seed,
        split=split,
        generator_version=config.generator_version,
        policy_version=policy.version,
        generated_at=config.as_of.astimezone(UTC),
        customers=builder.customers,
        profiles=builder.profiles,
        accounts=builder.accounts,
        counterparties=builder.counterparties,
        devices=builder.devices,
        transactions=builder.transactions,
        fingerprint="pending",
    )
    bundle = bundle.model_copy(update={"fingerprint": _fingerprint(bundle)})
    return GenerationResult(runtime=bundle, annotations=builder.annotations)
