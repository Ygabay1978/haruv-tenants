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

## Committee notes and messages

The committee dashboard opens `/admin` on the portal. Access requires an ordinary email OTP session, a currently active apartment membership and a currently active row in `portal.administrators`. No administrator email or credential is embedded in public code. The private setup SQL grants the owner's requested administrative email. Removing that row immediately blocks admin operations.

Notes and messages can target one apartment or all apartments, then owners, tenants or both. Every resident response filters recipients on the server against current roles for that exact apartment. Messages appear only after authentication. No notification emails/SMS are sent. Editors can update or unpublish messages; version checks prevent overwriting concurrent edits. Resident financial data and membership grants remain read-only in this editor.

The resident summary is rebuilt from explicit fields, excluding bank balances and their hidden JSON. Due warnings use monthly arrears through the current Jerusalem calendar month, cap at the outstanding annual amount, and exclude future months. Over two monthly fees shows a payment warning; over three shows a legal-collection warning phrased as a possible next step. Payment amounts use red for zero/unpaid and green for paid. EV records, unit details and contact cards are scoped to authorized apartments.

Resident-view troubleshooting uses a separate, read-only `resident_viewers` grant. After normal email authentication, authorized viewers can choose an apartment and owner/tenant perspective in the portal. `/api/preview` checks the grant on every request and uses the resident payload allowlist and the selected role's notices. It never creates an impersonated session or changes apartment memberships, and a viewer grant does not authorize announcement editing. Grant and revoke this role only in the private database; keep real account addresses out of this repository.

Committee capabilities are also bound to a single private `committee_account` identity. Extra admin/viewer rows do not authorize another account. Normal resident requests remain scoped to the signed-in resident's active apartment memberships.

Publishing a new or changed active notice queues a durable email attempt. Recipients come from distinct active email memberships matching the apartment and owner/tenant audience. The email includes the title and a normal portal sign-in link; the full notice remains behind authentication. Brevo message versions keep recipient addresses private, and each batch has a stable idempotency UUID. Saving unchanged text or hiding a notice sends no email. Admins see provider acceptance, missing recipients, definite failure, or uncertain status. Only pending/definitely failed attempts can be retried; unknown outcomes are not automatically resent. Tests never send real emails.


## Inline committee management and private attachments
The owner-private committee Site manages notices inline using a short-lived, memory-only bearer authorization obtained through a first-party portal popup. Both the exact dashboard origin and the singleton committee account are checked on every request; the grant expires with its parent login and permits only administration endpoints. No resident is granted committee access.

Notices support recoverable deletion and restoration as unpublished drafts. Attachments are stored in the private database, never in this repository. Up to five files per notice, 5 MB each and 15 MB total: JPEG/PNG/WebP, PDF, UTF-8 text, or non-macro Office documents. Download authorization checks active membership, apartment, audience and notice visibility. Draft, deleted and unrelated notices are unavailable to residents.

Apartment cards switch immediately for the committee, show explicit EV ownership, compact payment rows with EV charges where applicable, and a receipt-number column. Receipt values remain blank until supplied through monthlyReceipts; receipt generation is not implemented.


## First-party monitoring
The private committee Site Monitoring tab uses the same singleton owner authorization as notice management. POST /api/admin/monitoring supports 1/7/30/90 days and optional committee activity. Resident access is denied. Authenticated /api/usage accepts only fixed page labels, derives identity from the session, validates apartment membership and throttles duplicate page views. Automatic UI refreshes are not page views; committee previews do not send client events. View counts reflect visible sections or feature opens, not separate URLs. Gym booking clicks are outbound clicks, not completed Calendly reservations.

Login/logout, coarse browser/platform, authenticated views and downloads are retained privately for 90 days, along with a non-authenticating derived visit key. No IPs, OTP codes, raw session tokens, document names or notice contents are stored in usage events. Visible-page activity heartbeats count approximate active minutes, limited to five minutes since the last interaction. Public login email requests without active membership are not tracked. OTP email counts start at activation; older notice notification states remain available from existing records. Provider acceptance is explicitly distinguished from delivery. No delivery/open webhook tracking is implemented. Telemetry failures must not block sign-in. All times/buckets use Asia/Jerusalem.


## Resident directory and service providers
Owner-only POST /api/admin/directory/import updates contact display names and gym/PAL labels while preserving apartment finances and existing login memberships. It does not provision or revoke login accounts. Missing email/phone values are retained only when the same person can be identified unambiguously. Permission names expand only for a unique token match within that apartment; unmatched or ambiguous names are retained.

The authenticated portal shows gym/PAL names inline and has right-side navigation for the apartment, building summary and service directory. Only the singleton committee administrator can create, edit or unpublish service providers through /api/admin/services; residents get active entries and the informational disclaimer from /api/services. Unpublished records remain recoverable through editing. No fictitious providers are seeded. Links permit only HTTP/HTTPS, and phone links contain digits and telephone punctuation only.
