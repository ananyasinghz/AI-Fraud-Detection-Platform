"""Named, versioned dispatch for query-scoped feature operations."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.data.query_scope import QueryScope
from backend.app.data.repositories import TransactionRepository
from backend.app.domain.enums import EntityType
from backend.app.domain.features import FeatureRequest, FeatureResult
from backend.app.policy.config import PolicyConfig
from backend.app.tools.features.operations.aggregates import OPERATIONS as AGGREGATE_OPERATIONS
from backend.app.tools.features.operations.common import (
    Operation,
    OperationContext,
    result_for,
)
from backend.app.tools.features.operations.patterns import OPERATIONS as PATTERN_OPERATIONS
from backend.app.tools.features.operations.profiles import OPERATIONS as PROFILE_OPERATIONS

DEFAULT_OPERATION_VERSION = "v1"


class UnknownFeatureOperationError(LookupError):
    """Raised when no exact name/version registration exists."""


@dataclass(frozen=True, slots=True)
class RegisteredOperation:
    name: str
    version: str
    implementation: Operation


class FeatureRegistry:
    """Dispatch feature calculations against an already-resolved scope."""

    def __init__(self) -> None:
        self._operations: dict[tuple[str, str], RegisteredOperation] = {}

    def register(self, name: str, version: str, implementation: Operation) -> None:
        key = (name, version)
        if key in self._operations:
            raise ValueError(f"feature operation already registered: {name}@{version}")
        self._operations[key] = RegisteredOperation(name, version, implementation)

    def registered(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._operations))

    def dispatch(
        self,
        *,
        session: Session,
        policy: PolicyConfig,
        request: FeatureRequest,
        scope: QueryScope,
    ) -> FeatureResult:
        """Execute one exact registration without resolving or widening its scope."""
        _validate_resolved_scope(request, scope)
        registration = self._operations.get((request.operation, request.version))
        if registration is None:
            raise UnknownFeatureOperationError(
                f"unknown feature operation: {request.operation}@{request.version}"
            )
        transactions = tuple(TransactionRepository(session).list_scoped(scope))
        context = OperationContext(
            session=session,
            policy=policy,
            request=request,
            scope=scope,
            transactions=transactions,
        )
        return result_for(context, registration.implementation(context))

    __call__ = dispatch


def _validate_resolved_scope(request: FeatureRequest, scope: QueryScope) -> None:
    if scope.as_of != request.as_of:
        raise ValueError("resolved scope as_of must match the feature request")
    if (
        scope.start_inclusive < request.window.start_inclusive
        or scope.end_exclusive > request.window.end_exclusive
    ):
        raise ValueError("resolved scope cannot widen the feature request window")
    requested_ids = set(request.scope.entity_ids)
    if request.scope.entity_type is EntityType.CUSTOMER:
        scoped_ids = set(scope.customer_ids)
    elif request.scope.entity_type is EntityType.ACCOUNT:
        scoped_ids = set(scope.account_ids)
    else:
        scoped_ids = set(scope.transaction_ids)
    if not scope.is_empty and (not scoped_ids or not scoped_ids.issubset(requested_ids)):
        raise ValueError("resolved scope must preserve the explicit entity scope")

    transaction_filter = request.transaction_filter
    _validate_subset(scope.transaction_types, transaction_filter.transaction_types, "types")
    _validate_subset(scope.channels, transaction_filter.channels, "channels")
    _validate_subset(scope.countries, transaction_filter.countries, "countries")
    if transaction_filter.directions and (
        not scope.directions or not set(scope.directions).issubset(transaction_filter.directions)
    ):
        raise ValueError("resolved scope must preserve transaction directions")
    if (
        transaction_filter.currency is not None
        and scope.currency != transaction_filter.currency
        and not scope.is_empty
    ):
        raise ValueError("resolved scope must preserve transaction currency")
    if transaction_filter.minimum_amount_minor is not None and (
        scope.minimum_amount_minor is None
        or scope.minimum_amount_minor < transaction_filter.minimum_amount_minor
    ):
        raise ValueError("resolved scope must preserve minimum amount")
    if transaction_filter.maximum_amount_minor is not None and (
        scope.maximum_amount_minor is None
        or scope.maximum_amount_minor > transaction_filter.maximum_amount_minor
    ):
        raise ValueError("resolved scope must preserve maximum amount")


def _validate_subset(
    scoped: tuple[str, ...],
    requested: tuple[str, ...],
    label: str,
) -> None:
    if requested and (not scoped or not set(scoped).issubset(requested)):
        raise ValueError(f"resolved scope must preserve transaction {label}")


def build_feature_registry() -> FeatureRegistry:
    registry = FeatureRegistry()
    operations = {
        **AGGREGATE_OPERATIONS,
        **PATTERN_OPERATIONS,
        **PROFILE_OPERATIONS,
    }
    for name, implementation in operations.items():
        registry.register(name, DEFAULT_OPERATION_VERSION, implementation)
    return registry


FEATURE_REGISTRY = build_feature_registry()

__all__ = [
    "DEFAULT_OPERATION_VERSION",
    "FEATURE_REGISTRY",
    "FeatureRegistry",
    "RegisteredOperation",
    "UnknownFeatureOperationError",
    "build_feature_registry",
]
