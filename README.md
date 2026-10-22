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

## Deployment requirements (not yet provisioned)

An HTTPS Docker host with a persistent, private disk mounted at `/data`, plus a Twilio account and Verify service with SMS delivery to Israel enabled. This repository does not create accounts, accept terms, purchase plans or send SMS automatically. Configure Twilio spending limits and alerts before launch. Do not deploy on an ephemeral disk, GitHub Pages, or a multi-replica host with separate SQLite disks.

Environment variables are listed in `.env.example`. Set actual values in the host's secret configuration. `PORTAL_ORIGIN` must match the exact HTTPS origin, without trailing slash. Run the Docker container as its configured non-root user. The app listens on `$PORT` (default 8080) behind the host's TLS proxy. Health check: `/health`. Do not mount `/data` as a web directory.

## Private data import

Place trusted copies of both original dashboard HTML files on the private host, outside the Git checkout and web root. Set `PORTAL_DB`, then run:

```sh
python import_data.py --full /private/building57_dashboard.html --tenants /private/building57_tenants.html
```

Import runs atomically. It reads owner1Phone, owner1AltPhone, owner2Phone, tenant1Phone, tenant2Phone, tenant3Phone. Invalid/ambiguous phone values are skipped rather than guessed. Counts are printed without contact details. Verify skipped entries privately. Grant access only after verifying the source directory is current. New contacts become active on import; explicitly disabled retained contacts stay disabled. Contacts absent from a subsequent import lose access immediately.

For a specific membership, use parameterized SQL in a private administrative session to set `memberships.active=0`. To restore it, set it to 1 after verifying the number and apartment. No public admin token or browser-side administrator bypass exists.

Re-import updated source files to update the portal on the same URL. Changes in a chat do not directly trigger imports: an authorized agent/operator must apply and import the change. Back up the private SQLite database before imports and restrict backup access. Delete temporary uploaded source copies when no longer required.

## Validation

```sh
python -m unittest -v test_security.py
```

Tests mock the SMS provider and cover per-apartment isolation, owner/tenant access, unknown-number rejection, revocation, CSRF checks, OTP outcome handling, secure cookies, throttling, logout and read-only API behavior. Live SMS delivery, deployment, restored backups and the final phone allowlist still require validation before distributing a link.
