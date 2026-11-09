# Architecture

## Backend boundaries

The backend is organized into API, application, domain, and infrastructure
layers. `create_app` constructs the FastAPI application and owns its settings,
async SQLAlchemy engine, and shutdown lifecycle. HTTP dependencies provide
request-scoped sessions; services compose application behavior; repositories
mediate database access. Routes must not access the database directly.

The `/health` and `/api/v1/health` routes are process-liveness checks. The
`/ready` and `/api/v1/ready` routes execute a database probe through the
readiness service and repository; infrastructure failures produce HTTP 503.
The generic repository does not commit transactions, leaving transaction
ownership with application services.

Database configuration is loaded through pydantic-settings. Credentials use
`SecretStr`, structured logs omit connection URLs, and Alembic reads the same
validated settings as the application. Commerce domain services own
transactions and use typed repositories; API routes do not access the
database. The domain models share UUID primary keys and timezone-aware
`created_at`/`updated_at` columns. The initial domain migration creates users,
vendors, transactions, disputes, invoices, payouts, agents, decisions, and
audit logs.

Financial records are vendor-scoped, with composite foreign keys preventing a
dispute or decision from crossing vendor boundaries. Payout state checks
require an attributed human approval before execution states. Agent decisions
are pending recommendations and need a human reviewer to be approved or
rejected. User, vendor, and agent records may be soft-deleted; financial and
audit records are retained. Audit log entries are append-only and use a
polymorphic entity reference because they can target any domain entity.

## PayPal integration boundary

`app.integrations.paypal` owns async PayPal HTTP transport, OAuth token caching,
typed API clients, transient retry policy, and a circuit breaker. The
application factory owns the shared transport lifecycle and exposes API clients
through a dependency provider; clients also accept injected transports for
testing. PayPal credentials and sandbox/live selection come from validated
settings. Logs include safe operation metadata, never credentials or request
bodies.

The default approval verifier rejects payout creation, order capture, and
dispute-evidence submission. An application service must inject a verifier
that confirms the persisted human decision before these operations can reach
PayPal. Webhook verification returns PayPal's explicit success/failure status;
consumers must fail closed on anything other than `SUCCESS`.

## Dispute-defense agent

The dispute agent lives in `backend/app/agents/dispute/` and its LangGraph
workflow in `backend/app/workflows/dispute/`. It verifies incoming PayPal
signatures before looking up local disputes, gathers vendor-scoped transaction
data, a PayPal order, and injected shipping/communication evidence providers.
The provider contract requires redacted summaries; only bounded, validated
evidence is placed in the generated draft and persisted audit snapshot.

The success score is a transparent, non-calibrated heuristic. Each run creates
a pending `Decision` and append-only `AuditLog` snapshot; it never submits from
the analysis path. A separate service call records an active admin/operator's
approval and resumes the graph. The PayPal client independently re-verifies
that persisted approval before sending evidence. A durable submission-start
audit record prevents retries after any attempt, including an ambiguous network
result; such cases require manual reconciliation.

Narrative generation uses the async OpenAI client configured with
`OPENAI_API_KEY` and `DISPUTE_NARRATIVE_MODEL`. Evidence-provider adapters are
injected by the application and should raise
`TransientEvidenceProviderError` only for safe, temporary read failures. This
step adds no HTTP routes. A unique audit index makes webhook event handling
idempotent; apply its migration with the existing Alembic workflow.

## Invoice compliance agent

The invoice workflow in `backend/app/agents/invoice/` performs tenant-scoped
duplicate and completeness checks, creates a pending `Decision`, and stores a
redacted assessment snapshot in the append-oriented audit log. Duplicate
detection uses normalized invoice number or the combination of amount,
currency, billing email, and due date. Summaries omit invoice numbers and
billing email addresses. Review approval only records a human decision; it does
not send or alter an invoice.

## Smart payout agent

The payout workflow in `backend/app/agents/payout/` scores recent, same-currency
payout history, flags matching active payouts and amounts above three times the
90-day settled median, and creates a pending `Decision`. Fewer than three
settled records lowers confidence; missing history never authorizes payout by
itself. PayPal receiver data is payout-specific and optional for existing
records; only records with a configured recipient can be recommended for
approval. Recipient addresses are excluded from AI prompts, logs, and audit
snapshots.

`SmartPayoutService.approve_and_submit` requires an active admin/operator and
an approved persisted decision. It records approval and a durable one-shot
submission marker before calling PayPal with a deterministic idempotency key.
Failures require manual reconciliation and cannot be automatically replayed.
The payout is marked processing only after PayPal acknowledges batch creation.

## Financial action safety

AI-generated recommendations are not authorizations. Any future payout,
dispute submission, or other financial operation must be gated by a recorded
human approval before execution.

## Launch infrastructure

Realtime events use `app.events.EventBus`; the Redis implementation derives
each Pub/Sub channel from the authenticated tenant UUID. The event API streams
validated envelopes over SSE and the frontend BFF forwards only that route.
Notifications are a typed message on this transport, not a new domain action.
Pub/Sub is best-effort and does not retain or replay notifications. Producers
must be added separately; agent, commerce, and PayPal code does not publish
events.

`RequestObservabilityMiddleware` adds request IDs, route-template Prometheus
metrics, structured request logs, and spans when an OTLP endpoint is configured.
The scrape route requires an explicit bearer token. Sentry and OTLP export are
opt-in; request payloads and PII are not attached to telemetry.

The Render Blueprint provisions API, web, PostgreSQL, and private Redis
services. Alembic runs before each paid API deploy. The demo generator uses
deterministic IDs, is opt-in, refuses production, and creates payout requests
only in `pending_approval`.