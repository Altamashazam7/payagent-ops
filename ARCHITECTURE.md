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
validated settings as the application. The initial schema defines shared UUID
and timestamp model columns; domain tables and their migrations should be
introduced with the corresponding domain feature.

## Financial action safety

AI-generated recommendations are not authorizations. Any future payout,
dispute submission, or other financial operation must be gated by a recorded
human approval before execution.