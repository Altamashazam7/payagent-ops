"""Authentication and role-gate tests for commerce reporting endpoints."""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth.dependencies import get_current_user
from app.core.auth.jwt import UserContext
from app.models.enums import UserRole


def test_reporting_and_copilot_routes_require_authentication(
    client: TestClient,
) -> None:
    for path in (
        "/api/v1/dashboard/summary",
        "/api/v1/disputes",
        "/api/v1/invoices",
        "/api/v1/payouts",
        "/api/v1/activity",
        "/api/v1/copilot/insights",
    ):
        response = client.get(path)
        assert response.status_code == 401

    answer_response = client.post(
        "/api/v1/copilot/ask",
        json={"question": "What changed this month?"},
    )
    assert answer_response.status_code == 401


def test_viewer_cannot_access_copilot(
    application: FastAPI,
    client: TestClient,
) -> None:
    viewer = UserContext(
        sub=uuid4(),
        email="viewer@example.test",
        tenant_id=uuid4(),
        role=UserRole.VIEWER,
    )
    application.dependency_overrides[get_current_user] = lambda: viewer

    response = client.get("/api/v1/copilot/insights")

    assert response.status_code == 403
