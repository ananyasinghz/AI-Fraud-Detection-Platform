"""Grouped feature operation implementations."""

from backend.app.tools.features.operations.aggregates import OPERATIONS as AGGREGATE_OPERATIONS
from backend.app.tools.features.operations.patterns import OPERATIONS as PATTERN_OPERATIONS
from backend.app.tools.features.operations.profiles import OPERATIONS as PROFILE_OPERATIONS

__all__ = ["AGGREGATE_OPERATIONS", "PATTERN_OPERATIONS", "PROFILE_OPERATIONS"]
