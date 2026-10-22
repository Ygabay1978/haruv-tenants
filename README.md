# Haruv tenant portal

Read-only resident portal for building Haruv, Shtulim 57. Public repository contains application code only. No apartment data, contact directory, bank balances, uploaded HTML, or provider secrets belong here.

## Implemented

- Exact allowlisted email addresses, normalized to lowercase and mapped directly to owner/tenant apartment roles. No phone-to-email inference.
- Six-digit email OTP via Brevo HTTPS API, 10-minute expiry, HMAC-protected stored codes, atomic single-use verification and five attempts per ten minutes. Old SMS sessions are never accepted.
- Every protected request checks current membership on the server. Removing a tenant blocks existing sessions too.
- Opaque one-hour sessions stored as hashes, Secure/HttpOnly/SameSite cookies, exact-origin POST checks, bounded request bodies, shared transactional rate limits and a global email cap.
- Apartment responses whitelist financial fields only, plus owner/tenant names and recorded gym/PAL access for the authorized apartment only, without contact emails/phones, committee notes or other apartments. The original read-only TENANTS summary is stored privately and returned only after authentication.
- Residents have no write endpoints. Updates and membership changes are privileged server operations, not resident functions. The existing committee dashboard stays separate.
- Browser rechecks its data each minute. Authenticated responses use no-store.

## Deployment

The application supports Render Free with an external Neon Postgres database. Set `DATABASE_URL` to the complete Neon pooled connection URI in Render's secret environment settings. Keep the password out of GitHub, screenshots and chat. The server enforces TLS certificate verification for Neon connections and does not fall back to local storage on Render. All data, memberships, session hashes and email rate limits are stored in Neon, under the private `portal` SQL schema, so Render restarts do not remove them. No Neon browser Data API is enabled or needed.

Render region and Neon region: Frankfurt. `PORTAL_ORIGIN` must be the exact HTTPS origin (`https://haruv-tenants.onrender.com`), with no trailing slash. Keep Render health path `/health`; it deliberately does not wake Neon. `/api/status` checks database connectivity and returns setup booleans, never connection strings, contacts or financial data. It is diagnostic, not a way to authenticate or access data.

Use `gunicorn server:app` through the supplied Dockerfile. Render supplies `PORT`; do not override it. No persistent Render disk is required in Neon mode. The free hosting/database providers have usage limits and can sleep when inactive. Email authentication requires `BREVO_API_KEY`, a verified `EMAIL_FROM` sender, and a random `OTP_SECRET` of at least 32 characters set privately in Render. Sender/domain verification and live delivery must be completed before distributing the link. The application caps code requests at 200 per rolling day and 50 per hour; keep the provider account on its Free plan. No SMS fallback is implemented. Provider delivery errors are hidden from anonymous users and invalidate the pending code; check the provider dashboard for delivery diagnostics. The application never logs codes or provider response bodies.

For local development, omit `DATABASE_URL` and set `PORTAL_DB` to a private SQLite path. SQLite mode is disabled whenever `RENDER` is present.

## Private data import

Run this from a trusted administrative environment with `DATABASE_URL` set privately to the Neon URI. Keep both original HTML inputs outside the Git checkout and web root. Never pass credentials as CLI arguments. Then run:

```sh
python import_data.py --full /private/building57_dashboard.html --tenants /private/building57_tenants.html
```

Import runs atomically. It reads owner1Email, owner2Email, tenant1Email, tenant2Email, tenant3Email. Missing/invalid emails are skipped rather than guessed. Counts are printed without contact details. Verify source ownership privately. New contacts become active on import; explicitly disabled retained contacts stay disabled. Contacts absent from a subsequent import lose access immediately.

For a specific membership, use parameterized SQL in a private administrative session to set `email_memberships.active=0`. To restore it, set it to 1 after verifying the email and apartment. No public admin token or browser-side administrator bypass exists.

Re-import updated source files to update the portal on the same URL. Changes in a chat do not directly trigger imports: an authorized agent/operator must apply and import the change. Back up the private database before imports and restrict backup access. Delete temporary uploaded source copies when no longer required.

## Validation

```sh
python -m unittest -v test_security.py test_storage.py
```

Tests mock the email provider and cover per-apartment isolation, owner/tenant access, unknown-email rejection, revocation, CSRF checks, OTP outcome handling, secure cookies, throttling, logout and read-only API behavior. Live email delivery, deployment, restored backups and the final email allowlist still require validation before distributing a link.

For PostgreSQL integration testing against a disposable database only, set `TEST_DATABASE_URL` and run the same suite. Never point integration tests at production: each test clears the private portal tables.

## Resident page and imagery

The interface uses walnut, ivory and muted brass tones. Recorded gym and PAL permissions are view-only; neither button opens a door nor modifies grants. Missing entries are labelled as unrecorded, not inferred. Apartment payloads include owners, tenants and access strings imported from the corresponding directory row.

The selected neighborhood photo is intentionally visible on the public sign-in page as well as the authenticated apartment page. It is stored in the private database presentation table, never alongside resident data in the public repository. The `/building-photo` endpoint returns only a validated JPEG/PNG/WebP; it cannot return apartment data. Privately import the prepared metadata SQL for existing installations. Future imports retain names/access and use the photo embedded in the supplied tenant HTML. No resident upload or edit endpoint exists.
