"""FastAPI foundation integration tests."""

from uuid import UUID

from fastapi import Request
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.main import create_app


def make_client(**overrides: object) -> TestClient:
    values: dict[str, object] = {
        "environment": "test",
        "app_name": "Test Detection API",
    }
    values.update(overrides)
    settings = Settings.model_validate(values)
    return TestClient(create_app(settings))


def test_health_returns_contract_and_request_id() -> None:
    client = make_client()

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "Test Detection API"
    assert response.json()["contract_version"] == "v1"
    assert response.headers["X-Request-ID"]


def test_health_preserves_safe_caller_request_id() -> None:
    client = make_client()
    response = client.get("/api/v1/health", headers={"X-Request-ID": "demo-req:123"})

    assert response.headers["X-Request-ID"] == "demo-req:123"


def test_health_replaces_unsafe_request_id() -> None:
    client = make_client()
    response = client.get("/api/v1/health", headers={"X-Request-ID": "unsafe request id"})

    assert response.headers["X-Request-ID"] != "unsafe request id"
    UUID(response.headers["X-Request-ID"])


def test_custom_api_prefix_and_openapi() -> None:
    client = make_client(api_prefix="/custom/v1")

    assert client.get("/custom/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 404
    schema = client.get("/openapi.json").json()
    assert "/custom/v1/health" in schema["paths"]


def test_app_instances_keep_isolated_settings() -> None:
    first = make_client(app_name="First API")
    second = make_client(app_name="Second API")

    assert first.get("/api/v1/health").json()["service"] == "First API"
    assert second.get("/api/v1/health").json()["service"] == "Second API"


def test_app_error_uses_safe_envelope_and_request_id() -> None:
    app = create_app(Settings(environment="test"))

    @app.get("/test-error", response_model=None)
    async def test_error(request: Request) -> None:
        assert request.state.request_id
        raise AppError(
            code="TEST_FAILURE",
            message="Safe failure",
            status_code=409,
            details={"field": "example"},
        )

    client = TestClient(app)
    response = client.get("/test-error", headers={"X-Request-ID": "req-error-1"})

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "TEST_FAILURE",
            "message": "Safe failure",
            "details": {"field": "example"},
            "request_id": "req-error-1",
        }
    }
