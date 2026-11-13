# PayAgent Ops frontend

The Next.js 15.5 App Router frontend provides authenticated dashboard,
disputes, invoices, payouts, activity, and copilot workspaces. Copy
`.env.example` to `.env.local` and configure the organization OIDC provider and
backend URL before signing in. Register this callback with the provider:

```text
http://localhost:3000/api/auth/callback/oidc
```

For a local demo without an OIDC provider, set `DEMO_AUTH_ENABLED=true` in
`frontend/.env.local`, the root `.env`, and `backend/.env`, and keep the backend
`ENVIRONMENT=development`. Run the frontend with `npm run dev` and use
**Continue as demo executive**. The mode is not registered outside Next.js
development and the backend rejects it unless its environment is development.

The browser never receives an OIDC access token. NextAuth keeps it in its
encrypted server-side session cookie, and the same-origin backend proxy
forwards it to FastAPI. The proxy allowlists read-only reporting endpoints and
the informational copilot question endpoint; it does not expose approval,
payout, dispute-submission, or arbitrary backend routes. Configure HTTPS for
both frontend and backend in production.

The identity provider must issue the backend's required `sub`, `email`,
`tenant_id`, and `role` claims. `sub` must identify an active local user,
`email` and `role` must match that user, and `tenant_id` must identify an active
tenant-owner user. The OIDC provider is responsible for issuing tenant claims
only to authorized members; the current domain has no separate membership
table.

AG Grid Enterprise is enabled. Set `NEXT_PUBLIC_AG_GRID_LICENSE_KEY` to the
organization's license key to remove its license watermark. This key is
intended for browser delivery; do not put server secrets in `NEXT_PUBLIC_*`
variables.

Install and run from this directory. The development server binds to localhost
only:

```bash
npm install
npm run dev
npm test
npm run lint
npm run typecheck
npm run build
```

The workspace polls reporting endpoints every 60 seconds. Grid CSV export is
limited to selected, already-loaded rows and does not trigger a financial
action.
