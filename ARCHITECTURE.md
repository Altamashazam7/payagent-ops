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

## Financial action safety

AI-generated recommendations are not authorizations. Any future payout,
dispute submission, or other financial operation must be gated by a recorded
human approval before execution.