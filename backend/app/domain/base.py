"""Shared strict model behavior for contract-v1."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Forbid silent schema drift at every component boundary."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


def is_timezone_aware(value: datetime) -> bool:
    """Return whether a datetime has a usable UTC offset."""
    return value.tzinfo is not None and value.utcoffset() is not None
