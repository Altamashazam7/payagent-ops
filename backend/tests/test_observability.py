"""HTTP correlation and metrics endpoint behavior."""

import re

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.settings import Settings
from app.main import create_app


def test_request_id_is_returned_and_metrics_require_authentication() -> None:
    application = create_app(
        Settings(
            database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
            environment="test",
            metrics_enabled=True,
            metrics_bearer_token=SecretStr("metrics-test-token"),
        )
    )
    with TestClient(application) as client:
        health = client.get("/health")
        unauthorized = client.get("/metrics")
        metrics = client.get(
            "/metrics",
            headers={"Authorization": "Bearer metrics-test-token"},
        )

    request_id = health.headers.get("x-request-id")
    assert request_id is not None
    assert re.fullmatch(r"[0-9a-f-]{36}", request_id)
    assert unauthorized.status_code == 401
    assert metrics.status_code == 200
    assert b"payagent_http_requests_total" in metrics.content


def test_metrics_endpoint_is_hidden_when_disabled() -> None:
    application = create_app(
        Settings(
            database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
            environment="test",
        )
    )
    with TestClient(application) as client:
        response = client.get("/metrics")

    assert response.status_code == 404
