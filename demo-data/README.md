# Synthetic demo dataset

Run the backend generator after applying database migrations:

```powershell
Set-Location backend
python -m scripts.generate_demo_data --confirm-demo-data
```

The generator refuses `ENVIRONMENT=production` and inserts one deterministic
demo tenant only once. It does not truncate or update existing data, use PayPal
credentials, contact external services, approve payouts, or submit dispute
evidence. Every generated provider reference is prefixed `DEMO-`; customer
emails and PayPal recipient addresses are omitted.

For authenticated dashboard access, configure the demo OIDC identity with the
UUID printed by:

```powershell
python -c "from app.demo_data.generator import DEMO_OWNER_ID; print(DEMO_OWNER_ID)"
```

Use the UUID as both `sub` and `tenant_id`, and assign the local demo owner's
email and `admin` role. Only do this with a dedicated identity provider and
disposable demo database.
