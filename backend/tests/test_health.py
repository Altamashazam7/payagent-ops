"""Health and readiness endpoint integration tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from app.api.dependencies import get_paypal_clients, get_readiness_service
from app.core.constants import API_VERSION, SERVICE_NAME
from app.integrations.paypal import PayPalClients
from app.services.readiness import ReadinessService


class UnavailableRepository:
    async def check_database(self) -> None:
        raise SQLAlchemyError("simulated dependency failure")


def test_versioned_health_endpoint_returns_process_liveness(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": API_VERSION,
    }


def test_root_health_endpoint_is_available_for_platform_probes(
    client: TestClient,
) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_checks_database_and_exposes_versioned_contract(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": SERVICE_NAME,
        "version": API_VERSION,
    }


def test_root_readiness_is_available_for_platform_probes(
    client: TestClient,
) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_root_readiness_alias_is_available_for_platform_probes(
    client: TestClient,
) -> None:
    response = client.get("/readiness")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_failed_readiness_check_returns_503_without_leaking_error(
    application: FastAPI,
    client: TestClient,
) -> None:
    application.dependency_overrides[get_readiness_service] = lambda: ReadinessService(
        UnavailableRepository()
    )

    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Required service is unavailable"}
    assert "simulated dependency failure" not in response.text


def test_versioned_health_and_readiness_are_documented(
    client: TestClient,
) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/health" in paths
    assert "/api/v1/ready" in paths
    assert "/health" not in paths
    assert "/ready" not in paths


def test_paypal_clients_are_resolved_from_application_state(
    application: FastAPI,
    client: TestClient,
) -> None:
    request = Request({"type": "http", "app": application})

    assert client.get("/health").status_code == 200
    assert isinstance(get_paypal_clients(request), PayPalClients)
    assert get_paypal_clients(request) is application.state.paypal_clients
