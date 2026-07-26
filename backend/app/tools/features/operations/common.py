"""Shared types and deterministic result construction for feature operations."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from sqlalchemy.orm import Session

from backend.app.data.models import Transaction
from backend.app.data.query_scope import QueryScope
from backend.app.data.repositories import AccountRepository
from backend.app.domain.enums import EntityType, ValueType
from backend.app.domain.features import (
    FeatureDenominator,
    FeatureProvenance,
    FeatureRequest,
    FeatureResult,
    FeatureValue,
    FeatureWarning,
)
from backend.app.policy.config import PolicyConfig

NO_DATA = FeatureWarning(code="NO_DATA", message="The resolved scope contains no transactions.")
INSUFFICIENT_DATA = FeatureWarning(
    code="INSUFFICIENT_DATA",
    message="The resolved scope does not contain enough observations for this feature.",
)


@dataclass(frozen=True, slots=True)
class OperationOutput:
    """Values and interpretation metadata produced by one operation."""

    values: tuple[FeatureValue, ...]
    denominators: tuple[FeatureDenominator, ...] = ()
    warnings: tuple[FeatureWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Explicit inputs available to every registered operation."""

    session: Session
    policy: PolicyConfig
    request: FeatureRequest
    scope: QueryScope
    transactions: tuple[Transaction, ...]

    @property
    def currency(self) -> str | None:
        currencies = {item.currency for item in self.transactions}
        if self.scope.currency is not None:
            currencies.add(self.scope.currency)
        return next(iter(currencies)) if len(currencies) == 1 else None

    def window_transactions(
        self,
        start: datetime,
        end: datetime,
    ) -> tuple[Transaction, ...]:
        """Restrict already-scoped rows; never issue a wider query."""
        return tuple(item for item in self.transactions if start <= item.occurred_at < end)

    def customer_ids(self) -> tuple[str, ...]:
        if self.request.scope.entity_type is EntityType.CUSTOMER:
            return tuple(self.request.scope.entity_ids)
        if self.request.scope.entity_type is EntityType.ACCOUNT:
            accounts = AccountRepository(self.session).get_many(
                tuple(self.request.scope.entity_ids)
            )
            return tuple(sorted({item.customer_id for item in accounts}))
        return tuple(sorted({item.customer_id for item in self.transactions}))

    def account_ids(self) -> tuple[str, ...]:
        if self.request.scope.entity_type is EntityType.ACCOUNT:
            return tuple(self.request.scope.entity_ids)
        return tuple(sorted({item.account_id for item in self.transactions}))


Operation = Callable[[OperationContext], OperationOutput]


def integer(name: str, value: int | None, *, unit: str | None = None) -> FeatureValue:
    return FeatureValue(name=name, value_type=ValueType.INTEGER, value=value, unit=unit)


def decimal(name: str, value: Decimal | None, *, unit: str | None = None) -> FeatureValue:
    return FeatureValue(name=name, value_type=ValueType.DECIMAL, value=value, unit=unit)


def boolean(name: str, value: bool | None) -> FeatureValue:
    return FeatureValue(name=name, value_type=ValueType.BOOLEAN, value=value)


def denominator(name: str, value: int | Decimal, unit: str) -> FeatureDenominator:
    return FeatureDenominator(name=name, value=value, unit=unit)


def warning(code: str, message: str) -> FeatureWarning:
    return FeatureWarning(code=code, message=message)


def money_unit(currency: str | None) -> str | None:
    return f"{currency}_minor" if currency is not None else None


def money_warning(context: OperationContext) -> tuple[FeatureWarning, ...]:
    if not context.transactions:
        return ()
    if context.currency is None:
        return (
            warning(
                "MIXED_CURRENCY",
                "Monetary aggregation is unavailable without one explicit transaction currency.",
            ),
        )
    return ()


def scoped_money_total(
    context: OperationContext,
    transactions: tuple[Transaction, ...] | None = None,
) -> Decimal | None:
    rows = context.transactions if transactions is None else transactions
    currencies = {item.currency for item in rows}
    if context.scope.currency is not None:
        currencies.add(context.scope.currency)
    if len(currencies) > 1:
        return None
    return sum((Decimal(item.amount_minor) for item in rows), Decimal(0))


def result_for(context: OperationContext, output: OperationOutput) -> FeatureResult:
    """Attach stable query/evidence lineage to an operation output."""
    request_json = context.request.model_dump(mode="json")
    scope_json = asdict(context.scope)
    for key, value in tuple(scope_json.items()):
        if isinstance(value, datetime):
            scope_json[key] = value.isoformat()
        elif isinstance(value, tuple):
            scope_json[key] = tuple(str(item) for item in value)
    evidence = tuple(
        (
            item.transaction_id,
            item.seed_run_id,
            item.occurred_at.isoformat(),
            item.amount_minor,
            item.currency,
        )
        for item in context.transactions
    )
    encoded = json.dumps(
        {"request": request_json, "scope": scope_json, "evidence": evidence},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = sha256(encoded).hexdigest()
    dataset_runs = ",".join(sorted({item.seed_run_id for item in context.transactions})) or "empty"
    dataset_version = f"dataset.{sha256(dataset_runs.encode()).hexdigest()[:16]}"
    warnings = list(output.warnings)
    if context.scope.is_empty:
        warnings.append(
            warning(
                "EMPTY_SCOPE",
                context.scope.empty_reason or "The resolved query scope is explicitly empty.",
            )
        )
    elif not context.transactions:
        warnings.append(NO_DATA)
    if len(context.transactions) == context.scope.limit:
        warnings.append(
            warning(
                "QUERY_LIMIT_REACHED",
                "The resolved query limit was reached; results may represent a bounded page.",
            )
        )
    return FeatureResult(
        request=context.request,
        values=output.values,
        denominators=output.denominators,
        warnings=tuple(dict.fromkeys(warnings)),
        provenance=FeatureProvenance(
            source=f"transactions:{digest[:24]}",
            dataset_version=dataset_version,
            operation_version=context.request.version,
            policy_version=context.policy.version,
            query_id=f"feature:{digest[:32]}",
        ),
    )


def subwindow_scope(scope: QueryScope, start: datetime, end: datetime) -> QueryScope:
    """Return a narrower scope while preserving every resolved predicate."""
    return replace(scope, start_inclusive=start, end_exclusive=end)
