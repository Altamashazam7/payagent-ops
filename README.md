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

Run tests, lint, type-checking, and migrations from `backend/`:

```powershell
python -m pytest
python -m ruff check app tests migrations
python -m mypy --strict app tests
python -m alembic upgrade head
```

Build the backend container from the repository root with
`docker build -f backend/Dockerfile backend`. Configure `DATABASE_URL` through
the deployment environment; do not bake credentials into the image.