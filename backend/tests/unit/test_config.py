"""Configuration and logging unit tests."""

import json
import logging

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings, get_settings
from backend.app.core.logging import JsonFormatter, configure_logging


def test_settings_defaults() -> None:
    settings = Settings.model_validate({})

    assert settings.environment == "development"
    assert settings.api_prefix == "/api/v1"
    assert settings.contract_version == "v1"
    assert settings.debug is False


def test_settings_normalize_prefix() -> None:
    settings = Settings.model_validate({"api_prefix": "/custom/v1/"})
    assert settings.api_prefix == "/custom/v1"


@pytest.mark.parametrize("prefix", ["", "/", "api/v1"])
def test_settings_reject_invalid_prefix(prefix: str) -> None:
    with pytest.raises(ValidationError, match="api_prefix"):
        Settings.model_validate({"api_prefix": prefix})


def test_settings_reject_invalid_environment_and_version() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"environment": "staging"})
    with pytest.raises(ValidationError):
        Settings.model_validate({"app_version": "latest"})


def test_cached_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRAUD_ENVIRONMENT", "test")
    monkeypatch.setenv("FRAUD_API_PREFIX", "/test/v1")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.environment == "test"
        assert settings.api_prefix == "/test/v1"
        assert get_settings() is settings
    finally:
        get_settings.cache_clear()


def test_json_formatter_contains_safe_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.__dict__["request_id"] = "req-123"

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "hello world"
    assert payload["request_id"] == "req-123"
    assert payload["level"] == "INFO"


def test_configure_logging_replaces_root_handlers() -> None:
    configure_logging("WARNING")
    root = logging.getLogger()

    assert root.level == logging.WARNING
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
