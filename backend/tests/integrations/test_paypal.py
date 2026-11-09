"""Mocked PayPal API integration and resilience tests."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.logging import JsonLogFormatter
from app.core.settings import Settings
from app.integrations.paypal import (
    CircuitBreaker,
    CreateInvoiceRequest,
    CreateOrderRequest,
    CreatePayoutBatchRequest,
    DisputeEvidence,
    DisputeEvidenceRequest,
    DisputeListQuery,
    HumanApproval,
    HumanApprovalVerifier,
    PayPalAPIError,
    PayPalApprovalRequiredError,
    PayPalCircuitOpenError,
    PayPalClients,
    PayPalConfigurationError,
    PayPalOAuthTokenManager,
    PayPalWebhookHeaders,
    SensitivePayPalAction,
    WebhookEvent,
    create_paypal_clients,
)
from app.integrations.paypal.approval import require_human_approval

Handler = Callable[[httpx.Request], httpx.Response]


def build_settings(
    *,
    credentials: bool = True,
    paypal_webhook_id: str | None = "WH-TEST-1",
) -> Settings:
    return Settings(
        environment="test",
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        paypal_client_id=SecretStr("test-client-id") if credentials else None,
        paypal_client_secret=(SecretStr("test-client-secret") if credentials else None),
        paypal_webhook_id=paypal_webhook_id,
        paypal_retry_attempts=2,
        paypal_retry_min_wait_seconds=0,
        paypal_retry_max_wait_seconds=0.1,
        paypal_circuit_breaker_failure_threshold=3,
        paypal_circuit_breaker_reset_seconds=0.01,
    )


def token_response(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/v1/oauth2/token"
    assert request.headers["authorization"].startswith("Basic ")
    return httpx.Response(
        200,
        json={
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )


def build_clients(
    handler: Handler,
    settings: Settings | None = None,
    approval_verifier: HumanApprovalVerifier | None = None,
) -> tuple[httpx.AsyncClient, PayPalClients]:
    config = settings or build_settings()
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(
        transport=transport,
        base_url=config.paypal_api_base_url,
    )
    return http_client, create_paypal_clients(
        config,
        http_client=http_client,
        approval_verifier=(
            approval_verifier
            if approval_verifier is not None
            else AllowingHumanApprovalVerifier()
        ),
    )


async def close_clients(
    http_client: httpx.AsyncClient,
    clients: PayPalClients,
) -> None:
    await clients.aclose()
    await http_client.aclose()


def make_approval() -> HumanApproval:
    return HumanApproval(
        reviewer_user_id=uuid4(),
        decision_id=uuid4(),
        approved_at=datetime.now(UTC),
    )


class AllowingHumanApprovalVerifier:
    def __init__(self) -> None:
        self.actions: list[SensitivePayPalAction] = []

    async def verify(
        self,
        approval: HumanApproval,
        *,
        action: SensitivePayPalAction,
    ) -> None:
        assert approval.decision_id.int > 0
        assert approval.reviewer_user_id.int > 0
        self.actions.append(action)


async def test_oauth_token_is_cached_across_concurrent_requests() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return token_response(request)

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api-m.sandbox.paypal.com",
    )
    manager = PayPalOAuthTokenManager(http_client, build_settings())
    try:
        tokens = await asyncio.gather(*(manager.get_access_token() for _ in range(8)))
    finally:
        await http_client.aclose()

    assert tokens == ["test-access-token"] * 8
    assert calls == 1


async def test_oauth_requires_credentials_without_sending_a_request() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return token_response(request)

    settings = build_settings(credentials=False)
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=settings.paypal_api_base_url,
    )
    try:
        manager = PayPalOAuthTokenManager(http_client, settings)
        with pytest.raises(PayPalConfigurationError, match="PAYPAL_CLIENT_ID"):
            await manager.get_access_token()
    finally:
        await http_client.aclose()

    assert calls == 0


async def test_orders_client_serializes_payload_and_reuses_oauth_token() -> None:
    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        if request.url.path == "/v1/oauth2/token":
            return token_response(request)
        api_calls += 1
        assert request.headers["authorization"] == "Bearer test-access-token"
        if request.method == "POST":
            assert request.url.path == "/v2/checkout/orders"
            assert request.headers["paypal-request-id"] == "ORDER-REQ-1"
            payload = request.read()
            assert b'"currency_code":"USD"' in payload
            return httpx.Response(
                201,
                json={"id": "ORDER-1", "status": "CREATED"},
            )
        assert request.url.path == "/v2/checkout/orders/ORDER-1"
        return httpx.Response(200, json={"id": "ORDER-1", "status": "APPROVED"})

    http_client, clients = build_clients(handler)
    try:
        order_request = CreateOrderRequest.model_validate(
            {
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "amount": {"currency_code": "USD", "value": "12.50"},
                        "description": "Order",
                    }
                ],
            }
        )
        created = await clients.orders.create_order(
            order_request,
            request_id="ORDER-REQ-1",
        )
        fetched = await clients.orders.get_order(created.id)
    finally:
        await close_clients(http_client, clients)

    assert created.status == "CREATED"
    assert fetched.status == "APPROVED"
    assert api_calls == 2


async def test_transient_get_retries_but_client_errors_do_not() -> None:
    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        if request.url.path == "/v1/oauth2/token":
            return token_response(request)
        api_calls += 1
        if request.url.path.endswith("/ORDER-RETRY"):
            if api_calls == 1:
                return httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE"})
            return httpx.Response(200, json={"id": "ORDER-RETRY", "status": "CREATED"})
        return httpx.Response(
            422,
            json={"name": "INVALID_REQUEST", "message": "Invalid order"},
        )

    http_client, clients = build_clients(handler)
    try:
        order = await clients.orders.get_order("ORDER-RETRY")
        with pytest.raises(PayPalAPIError) as error:
            await clients.orders.get_order("ORDER-BAD")
    finally:
        await close_clients(http_client, clients)

    assert order.status == "CREATED"
    assert error.value.status_code == 422
    assert api_calls == 3


async def test_dispute_reads_use_validated_filters() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response(request)
        paths.append(request.url.path)
        if request.url.path.endswith("/DISPUTE-1"):
            return httpx.Response(
                200,
                json={"dispute_id": "DISPUTE-1", "status": "UNDER_REVIEW"},
            )
        assert request.url.params["page"] == "2"
        assert request.url.params["page_size"] == "5"
        return httpx.Response(
            200,
            json={
                "items": [{"dispute_id": "DISPUTE-1", "status": "UNDER_REVIEW"}],
                "total_items": 1,
                "total_pages": 1,
            },
        )

    http_client, clients = build_clients(handler)
    try:
        dispute = await clients.disputes.get_dispute("DISPUTE-1")
        dispute_page = await clients.disputes.list_disputes(
            DisputeListQuery(page=2, page_size=5)
        )
    finally:
        await close_clients(http_client, clients)

    assert dispute.status == "UNDER_REVIEW"
    assert dispute_page.total_items == 1
    assert paths == [
        "/v1/customer/disputes/DISPUTE-1",
        "/v1/customer/disputes",
    ]


async def test_create_invoice_uses_typed_payload_and_idempotency_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response(request)
        assert request.method == "POST"
        assert request.url.path == "/v2/invoicing/invoices"
        assert request.headers["paypal-request-id"] == "INVOICE-REQ-1"
        payload = request.read()
        assert b'"invoice_number":"INV-1"' in payload
        return httpx.Response(
            201,
            json={"id": "INV2-1", "status": "DRAFT"},
        )

    http_client, clients = build_clients(handler)
    try:
        invoice_request = CreateInvoiceRequest.model_validate(
            {
                "detail": {
                    "invoice_number": "INV-1",
                    "currency_code": "USD",
                },
                "primary_recipients": [
                    {"billing_info": {"email_address": "buyer@example.com"}}
                ],
                "items": [
                    {
                        "name": "Service",
                        "quantity": "1",
                        "unit_amount": {
                            "currency_code": "USD",
                            "value": "20.00",
                        },
                    }
                ],
            }
        )
        invoice = await clients.invoices.create_invoice(
            invoice_request,
            request_id="INVOICE-REQ-1",
        )
    finally:
        await close_clients(http_client, clients)

    assert invoice.id == "INV2-1"
    assert invoice.status == "DRAFT"


async def test_payout_batch_requires_approval_and_uses_batch_idempotency() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response(request)
        assert request.url.path == "/v1/payments/payouts"
        assert request.headers["paypal-request-id"] == "BATCH-1"
        return httpx.Response(
            201,
            json={"payout_batch_id": "BATCH-1", "batch_status": "PENDING"},
        )

    verifier = AllowingHumanApprovalVerifier()
    http_client, clients = build_clients(handler, approval_verifier=verifier)
    try:
        request = CreatePayoutBatchRequest.model_validate(
            {
                "sender_batch_header": {
                    "sender_batch_id": "BATCH-1",
                    "email_subject": "Vendor payout",
                },
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "amount": {"currency_code": "USD", "value": "25.00"},
                        "receiver": "vendor@example.com",
                        "sender_item_id": "PAYOUT-1",
                    }
                ],
            }
        )
        payout = await clients.payouts.create_payout_batch(
            request,
            approval=make_approval(),
        )
    finally:
        await close_clients(http_client, clients)

    assert payout.batch_status == "PENDING"
    assert verifier.actions == [SensitivePayPalAction.CREATE_PAYOUT_BATCH]
    with pytest.raises(PayPalApprovalRequiredError):
        require_human_approval(None)


async def test_capture_and_dispute_evidence_require_approval() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response(request)
        paths.append(request.url.path)
        if request.url.path.endswith("/capture"):
            return httpx.Response(201, json={"id": "ORDER-1", "status": "COMPLETED"})
        return httpx.Response(
            200,
            json={"dispute_id": "DISPUTE-1", "status": "UNDER_REVIEW"},
        )

    verifier = AllowingHumanApprovalVerifier()
    http_client, clients = build_clients(handler, approval_verifier=verifier)
    approval = make_approval()
    try:
        capture = await clients.orders.capture_order(
            "ORDER-1",
            approval=approval,
        )
        dispute = await clients.disputes.provide_evidence(
            "DISPUTE-1",
            DisputeEvidenceRequest(
                evidence=[
                    DisputeEvidence(
                        evidence_type="PROOF_OF_FULFILLMENT",
                        evidence_info={"tracking_number": "TRACK-1"},
                    )
                ]
            ),
            approval=approval,
        )
    finally:
        await close_clients(http_client, clients)

    assert capture.status == "COMPLETED"
    assert dispute.status == "UNDER_REVIEW"
    assert paths == [
        "/v2/checkout/orders/ORDER-1/capture",
        "/v1/customer/disputes/DISPUTE-1/provide-evidence",
    ]
    assert verifier.actions == [
        SensitivePayPalAction.CAPTURE_ORDER,
        SensitivePayPalAction.SUBMIT_DISPUTE_EVIDENCE,
    ]


async def test_sensitive_operations_fail_closed_without_persisted_verifier() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return token_response(request)

    config = build_settings()
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=config.paypal_api_base_url,
    )
    clients = create_paypal_clients(config, http_client=http_client)
    payout_request = CreatePayoutBatchRequest.model_validate(
        {
            "sender_batch_header": {
                "sender_batch_id": "BATCH-1",
                "email_subject": "Vendor payout",
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {"currency_code": "USD", "value": "25.00"},
                    "receiver": "vendor@example.com",
                    "sender_item_id": "PAYOUT-1",
                }
            ],
        }
    )
    try:
        with pytest.raises(PayPalApprovalRequiredError, match="verifier is configured"):
            await clients.payouts.create_payout_batch(
                payout_request,
                approval=make_approval(),
            )
    finally:
        await close_clients(http_client, clients)

    assert calls == 0


async def test_webhook_verification_sends_required_headers_and_event() -> None:
    statuses = iter(("SUCCESS", "FAILURE"))
    received_webhook_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response(request)
        payload = request.read()
        received_webhook_ids.append(
            str(httpx.Response(200, content=payload).json()["webhook_id"])
        )
        return httpx.Response(
            200,
            json={"verification_status": next(statuses)},
        )

    http_client, clients = build_clients(handler)
    headers = PayPalWebhookHeaders.from_headers(
        {
            "PAYPAL-AUTH-ALGO": "SHA256withRSA",
            "PAYPAL-CERT-URL": "https://api-m.paypal.com/certs/CERT-1",
            "PAYPAL-TRANSMISSION-ID": "TRANSMISSION-1",
            "PAYPAL-TRANSMISSION-SIG": "signature",
            "PAYPAL-TRANSMISSION-TIME": "2026-11-09T10:00:00Z",
        }
    )
    event = WebhookEvent(
        id="EVENT-1",
        event_type="PAYMENT.CAPTURE.COMPLETED",
        resource_type="capture",
        resource={"id": "CAPTURE-1"},
    )
    try:
        success = await clients.webhooks.verify(headers, event)
        failure = await clients.webhooks.verify(headers, event)
    finally:
        await close_clients(http_client, clients)

    assert success.verification_status == "SUCCESS"
    assert failure.verification_status == "FAILURE"
    assert received_webhook_ids == ["WH-TEST-1", "WH-TEST-1"]


async def test_webhook_verification_requires_configured_webhook_id() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return token_response(request)

    config = build_settings(paypal_webhook_id=None)
    http_client, clients = build_clients(handler, config)
    headers = PayPalWebhookHeaders.from_headers(
        {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://api-m.paypal.com/certs/CERT-1",
            "paypal-transmission-id": "TRANSMISSION-1",
            "paypal-transmission-sig": "signature",
            "paypal-transmission-time": "2026-11-09T10:00:00Z",
        }
    )
    event = WebhookEvent(
        id="EVENT-1",
        event_type="PAYMENT.CAPTURE.COMPLETED",
        resource_type="capture",
        resource={"id": "CAPTURE-1"},
    )
    try:
        with pytest.raises(PayPalConfigurationError, match="PAYPAL_WEBHOOK_ID"):
            await clients.webhooks.verify(headers, event)
    finally:
        await close_clients(http_client, clients)

    assert calls == 0


def test_webhook_headers_require_complete_fields_and_https() -> None:
    with pytest.raises(ValueError, match="Missing PayPal webhook headers"):
        PayPalWebhookHeaders.from_headers({})

    with pytest.raises(ValidationError, match="HTTPS"):
        PayPalWebhookHeaders.model_validate(
            {
                "auth_algo": "SHA256withRSA",
                "cert_url": "http://example.test/cert",
                "transmission_id": "TRANSMISSION-1",
                "transmission_sig": "signature",
                "transmission_time": "2026-11-09T10:00:00Z",
            }
        )

    with pytest.raises(ValidationError, match="PayPal domain"):
        PayPalWebhookHeaders.model_validate(
            {
                "auth_algo": "SHA256withRSA",
                "cert_url": "https://paypal.com.attacker.test/cert",
                "transmission_id": "TRANSMISSION-1",
                "transmission_sig": "signature",
                "transmission_time": "2026-11-09T10:00:00Z",
            }
        )


async def test_circuit_breaker_opens_and_allows_one_half_open_probe() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=0.01)
    await breaker.before_call()
    await breaker.record_failure()

    assert str(breaker.state) == "open"
    with pytest.raises(PayPalCircuitOpenError):
        await breaker.before_call()

    await asyncio.sleep(0.02)
    await breaker.before_call()
    assert str(breaker.state) == "half_open"
    with pytest.raises(PayPalCircuitOpenError):
        await breaker.before_call()

    await breaker.record_success()
    assert str(breaker.state) == "closed"


def test_invalid_order_and_payout_amounts_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CreateOrderRequest.model_validate({"intent": "CAPTURE", "purchase_units": []})
    with pytest.raises(ValidationError):
        CreatePayoutBatchRequest.model_validate(
            {
                "sender_batch_header": {
                    "sender_batch_id": "BATCH-1",
                    "email_subject": "Payout",
                },
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "amount": {"currency_code": "USD", "value": "0"},
                        "receiver": "vendor@example.com",
                        "sender_item_id": "PAYOUT-1",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        CreateInvoiceRequest.model_validate(
            {
                "detail": {
                    "invoice_number": "INV-1",
                    "currency_code": "USD",
                },
                "primary_recipients": [
                    {"billing_info": {"email_address": "not-an-email"}}
                ],
                "items": [
                    {
                        "name": "Service",
                        "quantity": "1",
                        "unit_amount": {
                            "currency_code": "USD",
                            "value": "20.00",
                        },
                    }
                ],
            }
        )


def test_paypal_logs_emit_only_safe_structured_metadata() -> None:
    record = logging.getLogger("payagent_ops").makeRecord(
        "payagent_ops",
        logging.INFO,
        __file__,
        1,
        "PayPal request completed",
        (),
        None,
        extra={
            "event": "paypal_request_completed",
            "provider": "paypal",
            "operation": "v2.checkout.orders",
            "http_method": "GET",
            "status_code": 200,
            "access_token": "must-not-be-logged",
        },
    )

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["provider"] == "paypal"
    assert payload["operation"] == "v2.checkout.orders"
    assert payload["status_code"] == 200
    assert "access_token" not in payload


async def test_paypal_client_rejects_untrusted_paths_and_authorization_override() -> (
    None
):
    settings = build_settings()
    http_client, clients = build_clients(token_response, settings)
    try:
        with pytest.raises(ValueError, match="safe absolute API path"):
            await clients.api.request(
                "GET",
                "https://attacker.example",
                response_model=WebhookEvent,
            )
        with pytest.raises(ValueError, match="Authorization is managed"):
            await clients.api.request(
                "GET",
                "/v2/checkout/orders/ORDER-1",
                response_model=WebhookEvent,
                headers={"Authorization": "Bearer attacker-token"},
            )
        with pytest.raises(ValueError, match="idempotency_key"):
            await clients.api.request(
                "POST",
                "/v2/checkout/orders",
                response_model=WebhookEvent,
                idempotency_key="bad key",
            )
    finally:
        await close_clients(http_client, clients)
