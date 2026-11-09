# PayAgent Ops

PayAgent Ops is an operations platform for reviewing commerce activity and
assisting teams with payment workflows. Financial actions must remain subject
to explicit human approval.

## Backend foundation

The FastAPI application is in `backend/`. It uses a factory so configuration
is validated when the ASGI server starts, rather than at module import time.
From the repository root, copy `.env.example` to `backend/.env`, set
`DATABASE_URL` for your PostgreSQL instance, and install `requirements.txt` in a
Python 3.12 environment:

```powershell
Copy-Item .env.example backend\.env
Set-Location backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:create_app --factory --reload
```

The versioned API is documented at `/docs`. Liveness is available at
`/health` and `/api/v1/health`; readiness is available at `/ready` and
`/api/v1/ready`. Readiness probes PostgreSQL and returns HTTP 503 when it is
unavailable. Liveness does not assert dependency availability.

## Commerce domain foundation

The backend domain includes users, vendors, transactions, disputes, invoices,
payouts, agents, decisions, and append-only audit logs. Typed ORM models,
repositories, Pydantic schemas, and services live under `backend/app/`; no
commerce mutation endpoints are exposed. Commerce rows use UUID identifiers,
timezone-aware timestamps, vendor-scoped constraints, and indexed operational
queries. Users, vendors, and agents support soft deletion; financial and audit
records are retained.

Payouts start pending approval. Database constraints require an approving
operator and approval timestamp before a payout can enter an approved,
processing, or paid state. Agent decisions are recommendations; approval and
rejection require a human reviewer. Apply the domain migration with
`python -m alembic upgrade head` from `backend/`.

## PayPal integration foundation

Async clients for Orders, Disputes, Invoicing, Payouts, OAuth, and webhook
signature verification are in `backend/app/integrations/paypal/`. The
application-scoped clients are available through dependency injection and share
one `httpx` transport. Set `PAYPAL_ENVIRONMENT` to `sandbox` (the default) or
`live`, provide `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET`, and set
`PAYPAL_WEBHOOK_ID` to enable verification. Secrets are environment-driven and
excluded from logs.

Sensitive capture, dispute-evidence, and payout operations require both a
human-approval record and an injected persisted-approval verifier. The default
application composition has no verifier and fails closed; no financial action
can be submitted until an application service verifies the recorded decision.
Webhook consumers must process an event only when PayPal returns
`verification_status: SUCCESS`. No commerce or webhook routes are added in this
step.

## Dispute defense agent

The first LangGraph agent is implemented in
`backend/app/agents/dispute/` and `backend/app/workflows/dispute/`. Configure
`OPENAI_API_KEY` and optionally `DISPUTE_NARRATIVE_MODEL` to enable narrative
generation. The service receives the raw event plus PayPal signature headers
and verifies the signature itself before retrieving the local dispute or its
related order. Shipping and communication providers are injected; their
communication summaries must be redacted. Only explicitly transient,
read-only provider errors are retried.

Analysis creates a pending `Decision` with a persisted evidence snapshot and
draft narrative. The reported success probability is a heuristic, not a
calibrated prediction. To resume, the application calls
`DisputeDefenseService.approve_and_submit` with the decision ID and an active
admin/operator ID obtained from its authenticated request context. The service
records the approval, verifies it again against the database, and then submits
through PayPal. No dispute endpoint or background route is exposed in this
step. A logged submission attempt is one-shot; if its outcome is ambiguous,
reconcile with PayPal before taking further action.
The Step 5 migration adds a unique audit index for duplicate webhook-event
protection; the Step 7 migration adds optional payout recipients and a
normalized invoice-number search index. Apply all migrations with
`python -m alembic upgrade head`.

## Invoice and payout agents

The Invoice Compliance Agent checks invoice completeness and likely duplicates
and persists a human-reviewable recommendation. Duplicate matching compares
normalized invoice numbers and a strong amount/currency/customer/due-date
fingerprint. Review approval records a decision only; invoices are not sent or
changed automatically.

The Smart Payout Agent uses vendor-scoped payout history to flag duplicate and
large outlier requests. Set a payout-specific `paypal_receiver` and
`paypal_recipient_type` (`EMAIL`, `PHONE`, or `PAYPAL_ID`) when creating eligible
payouts. These nullable fields preserve existing records; the agent will not
fall back to the vendor merchant ID. A recommendation never moves money:
submission requires an active admin/operator's persisted approval. PayPal
requests use a stable batch idempotency key; ambiguous outcomes are one-shot and
must be reconciled manually. Both agents use the shared `OPENAI_API_KEY` and
their optional `INVOICE_COMPLIANCE_MODEL` and `PAYOUT_NARRATIVE_MODEL` settings.

## Executive reporting and workspaces

The API exposes tenant-scoped read-only reporting at
`/api/v1/dashboard/summary`, `/api/v1/dashboard/trends`, `/api/v1/disputes`,
`/api/v1/invoices`, `/api/v1/payouts`, and `/api/v1/activity`. Copilot
recommendations are available at `/api/v1/copilot/insights`; questions use
`POST /api/v1/copilot/ask`. All routes require a verified RS256 OIDC bearer
token and a matching active local user. Revenue and operational amounts remain
bucketed by currency. Payout recipient addresses and raw audit before/after
state are not included in reporting responses.

The OIDC token must carry `sub`, `email`, `tenant_id`, and `role` claims.
`sub`, `email`, and `role` are bound to an active local user. The current tenant
mapping treats `tenant_id` as the UUID of an active tenant-owner user; the OIDC
provider must only issue that tenant claim to authorized members because the
domain does not yet include a separate membership table. The dashboard role
set includes viewers; copilot access excludes viewers.

The Next.js 15.5 frontend lives in `frontend/`. It provides `/dashboard`,
`/disputes`, `/invoices`, `/payouts`, `/activity`, and `/copilot`, protected by
OIDC sign-in. Its same-origin BFF only forwards allowlisted reporting and
copilot requests. AG Grid bulk export is read-only; no financial approval,
dispute submission, or payout execution is exposed by these pages. See
`frontend/README.md` for OIDC callback setup, frontend environment variables,
and npm commands.

Run tests, lint, type-checking, and migrations from `backend/`:

```powershell
python -m pytest -q
python -m ruff check app tests migrations
python -m ruff format --check app tests migrations
python -m mypy --strict app tests migrations
python -m alembic upgrade head
```

Build the backend container from the repository root with
`docker build -f backend/Dockerfile backend`. Configure `DATABASE_URL` through
the deployment environment; do not bake credentials into the image.

## Launch readiness

The realtime layer uses Redis Pub/Sub and authenticated, tenant-scoped
server-sent events. It carries versioned event envelopes and notification
summaries; Pub/Sub is ephemeral, and no agent, commerce service, or PayPal
integration publishes events automatically. Set `REDIS_URL` to enable the
stream. The Next.js BFF forwards only the authenticated `/events/stream`
endpoint.

HTTP request logs include generated request IDs and route-template metrics.
Set `METRICS_ENABLED=true` and `METRICS_BEARER_TOKEN` together to expose the
protected `/metrics` scrape endpoint. Optional `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
and `SENTRY_DSN` settings enable tracing and error reporting. Neither is
required to start the API.

`docker-compose.yml` runs local PostgreSQL, Redis, and the API. For Render,
create the resources from [render.yaml](render.yaml), provide the prompted
identity-provider and integration secrets, and set `NEXTAUTH_URL` to the
frontend's HTTPS origin. The API migration runs as a paid web service's
pre-deploy command. See [the launch architecture](docs/architecture-launch.md)
for deployment assumptions and Redis limitations.

Generate synthetic, idempotent demo data only in a designated
non-production database:

```powershell
Set-Location backend
python -m alembic upgrade head
python -m scripts.generate_demo_data --confirm-demo-data
```

The generator refuses `ENVIRONMENT=production`. It creates only clearly
synthetic transactions, invoices, disputes, pending decisions, and pending
payout requests; it does not call PayPal or approve financial actions. See
[demo-data/README.md](demo-data/README.md), the [demo script](docs/demo-script.md),
the [hackathon story](docs/hackathon-story.md), and the
[pitch one-pager](docs/pitch-one-pager.md).