# Haruv tenant portal

Read-only resident portal for building Haruv, Shtulim 57. Public repository contains application code only. No apartment data, contact directory, bank balances, uploaded HTML, or SMS secrets belong here.

## Implemented

- Allowlisted Israeli mobile numbers, normalized to E.164; owners and tenants can share an apartment, and one phone can have multiple apartments.
- Twilio Verify handles real SMS code generation, expiry, and verification. No development codes or authentication bypass.
- Every protected request checks current membership on the server. Removing a tenant blocks existing sessions too.
- Opaque one-hour sessions stored as hashes, Secure/HttpOnly/SameSite cookies, exact-origin POST checks, bounded request bodies, shared transactional rate limits and a global SMS cap.
- Apartment responses whitelist financial fields only, without committee notes, the resident directory or other apartments. The original read-only TENANTS summary is stored privately and returned only after authentication.
- Residents have no write endpoints. Updates and membership changes are privileged server operations, not resident functions. The existing committee dashboard stays separate.
- Browser rechecks its data each minute. Authenticated responses use no-store.

## Deployment

The application supports Render Free with an external Neon Postgres database. Set `DATABASE_URL` to the complete Neon pooled connection URI in Render's secret environment settings. Keep the password out of GitHub, screenshots and chat. The server enforces TLS certificate verification for Neon connections and does not fall back to local storage on Render. All data, memberships, session hashes and SMS rate limits are stored in Neon, under the private `portal` SQL schema, so Render restarts do not remove them. No Neon browser Data API is enabled or needed.

Render region and Neon region: Frankfurt. `PORTAL_ORIGIN` must be the exact HTTPS origin (`https://haruv-tenants.onrender.com`), with no trailing slash. Keep Render health path `/health`; it deliberately does not wake Neon. `/api/status` checks database connectivity and returns setup booleans, never connection strings, contacts or financial data. It is diagnostic, not a way to authenticate or access data.

Use `gunicorn server:app` through the supplied Dockerfile. Render supplies `PORT`; do not override it. No persistent Render disk is required in Neon mode. The free hosting/database providers have usage limits and can sleep when inactive. SMS authentication still needs a Twilio account, Verify service and Israel delivery enabled. Configure provider spending limits before live SMS use. This code does not create paid accounts, accept terms or send messages automatically.

For local development, omit `DATABASE_URL` and set `PORTAL_DB` to a private SQLite path. SQLite mode is disabled whenever `RENDER` is present.

## Private data import

Run this from a trusted administrative environment with `DATABASE_URL` set privately to the Neon URI. Keep both original HTML inputs outside the Git checkout and web root. Never pass credentials as CLI arguments. Then run:

```sh
python import_data.py --full /private/building57_dashboard.html --tenants /private/building57_tenants.html
```

Import runs atomically. It reads owner1Phone, owner1AltPhone, owner2Phone, tenant1Phone, tenant2Phone, tenant3Phone. Invalid/ambiguous phone values are skipped rather than guessed. Counts are printed without contact details. Verify skipped entries privately. Grant access only after verifying the source directory is current. New contacts become active on import; explicitly disabled retained contacts stay disabled. Contacts absent from a subsequent import lose access immediately.

For a specific membership, use parameterized SQL in a private administrative session to set `memberships.active=0`. To restore it, set it to 1 after verifying the number and apartment. No public admin token or browser-side administrator bypass exists.

Re-import updated source files to update the portal on the same URL. Changes in a chat do not directly trigger imports: an authorized agent/operator must apply and import the change. Back up the private database before imports and restrict backup access. Delete temporary uploaded source copies when no longer required.

## Validation

```sh
python -m unittest -v test_security.py test_storage.py
```

Tests mock the SMS provider and cover per-apartment isolation, owner/tenant access, unknown-number rejection, revocation, CSRF checks, OTP outcome handling, secure cookies, throttling, logout and read-only API behavior. Live SMS delivery, deployment, restored backups and the final phone allowlist still require validation before distributing a link.

For PostgreSQL integration testing against a disposable database only, set `TEST_DATABASE_URL` and run the same suite. Never point integration tests at production: each test clears the private portal tables.
