# Four-minute demo script

## Before the room

1. Deploy the API and frontend from the Render Blueprint and check `/ready`.
2. Configure OIDC claims for the seeded demo owner. Read the owner UUID with:

   ```sh
   cd backend
   python -c "from app.demo_data.generator import DEMO_OWNER_ID; print(DEMO_OWNER_ID)"
   ```

   Use that UUID for both the demo user's subject and tenant claim. The
   identity provider must authorize this tenant mapping.
3. Apply migrations, then seed only the demo database:

   ```sh
   cd backend
   python -m alembic upgrade head
   python -m scripts.generate_demo_data --confirm-demo-data
   ```
4. Sign in through the configured OIDC provider. Confirm the workspace shows
   synthetic records and no real PayPal credentials are in use.

## The walkthrough

**0:00–0:40 — The operational problem.** Explain that the issue is fragmented
exception handling, not payment acceptance. Open the dashboard and call out
currency-separated revenue, dispute pressure, and pending work.

**0:40–1:35 — Dispute context.** Open Disputes and show a synthetic
needs-response case. Explain that an agent can gather transaction context and
prepare a recommendation, while submission remains behind explicit human
approval. Do not claim that this demo submits evidence.

**1:35–2:20 — Invoice and payout review.** Open Invoices and Payouts. Point out
the seeded pending recommendations and emphasize that synthetic payouts are
never approved, processed, or sent.

**2:20–3:05 — Executive copilot.** Ask a question about leakage or dispute
trends. Describe the response as analysis over aggregate reporting data, not a
financial instruction.

**3:05–3:40 — Launch readiness.** Open Activity and show the synthetic seed
entries. Explain tenant-scoped SSE notifications and that Redis Pub/Sub is
ephemeral; no workflow event producers are connected yet.

**3:40–4:00 — Close.** “PayAgent Ops turns payment exceptions into one
reviewable operating picture. AI prepares the work; people authorize the
money.”

## Safety checks

- Keep PayPal in sandbox; do not approve or submit actions during this demo.
- Never display environment variables, access tokens, or real customer data.
- If OIDC, Redis, or the copilot provider is unavailable, state that clearly
  and continue with the dashboard rather than implying the feature is live.
