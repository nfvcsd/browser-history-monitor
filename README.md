# Browser History Monitor — Collection controls

This repository contains the centralized Chrome history system with routed
Overview, Users, Domains, Reports, Time Spent, Audit Log and Settings pages:

- Chrome Manifest V3 extension
- FastAPI REST API
- PostgreSQL storage
- React + TypeScript dashboard
- Docker Compose development environment

## Security status

Dashboard authentication has two mutually exclusive modes:

- `AUTH_MODE=google`: verified Google Workspace sign-in plus an exact administrator
  email allowlist. The development administrator token is rejected in this mode.
- `AUTH_MODE=development`: shared `DEV_ADMIN_TOKEN` for local testing only.

The development Compose stack defaults to development mode for compatibility;
`.env.example` sets it explicitly. Running the backend directly defaults to
Google mode and denies access until configured. A typo in `AUTH_MODE` prevents
startup. Credentials from one mode cannot authenticate in the other.

Extension authentication is configured independently. Development mode retains
the shared token and unverified profile email. Enrolled mode uses Google-verified
profile identity and individual expiring device credentials. See the
[managed deployment guide](docs/managed-deployment.md) for Google Admin rollout,
including its mandatory fresh-profile silent-authentication pilot. This is profile
enrollment, not hardware attestation; production deployment hardening remains future work.

## Start the server

1. Copy the environment file:

   ```bash
   cp .env.example .env
   ```

2. Replace both development tokens and the PostgreSQL password with long random
   values.

3. Start the stack:

   ```bash
   docker compose up --build
   ```

4. Open:

   - Dashboard: http://localhost:5173
   - FastAPI docs: http://localhost:8000/docs
   - Health check: http://localhost:8000/health

5. In development mode, paste `DEV_ADMIN_TOKEN`. For Workspace sign-in, follow
   the Google setup section below before changing `AUTH_MODE`.

## Load the extension

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked**.
4. Select the `extension/` directory.
5. Open the extension's **Details** page and then **Extension options**.
6. Configure:
   - API URL: `http://localhost:8000`
   - Extension token: the value of `DEV_EXTENSION_TOKEN`
   - Initial history days: start with `7`
   - Fallback email only if Chrome profile identity is unavailable.
7. Click **Save and test sync**.

The extension performs:

- an initial history reconciliation on installation/configuration;
- an immediate attempt when `chrome.history.onVisited` fires;
- a periodic reconciliation every 5 minutes;
- server-side deduplication by device + Chrome visit ID.

## Current API

### Extension
- `POST /api/v1/sync/batch`

### Dashboard
- `GET /api/v1/overview`
- `GET /api/v1/users` — existing user list for filter menus
- `GET /api/v1/users/summary` — user identity, last sync, device and visit counts; `q`, `limit`, `offset`
- `GET /api/v1/users/{user_id}` — one user summary (404 if absent)
- `GET /api/v1/domains` — domain aggregation; `q`, `user_id`, `start`, `end`, `limit`, `offset`
- `GET /api/v1/history` — existing filters plus `exact_domain` for precise drill-downs
- `GET /api/v1/reports` — report summaries and activity aggregations
- `GET /api/v1/reports/export.csv` — streaming CSV of matching visits
- `GET /api/v1/audit` — authenticated audit log with filters and cursor pagination

Dashboard endpoints require the header for the selected mode:

```text
# AUTH_MODE=google
Authorization: Bearer <Google ID token>
# AUTH_MODE=development
X-Admin-Token: <DEV_ADMIN_TOKEN>
```

`GET /api/v1/auth/config` exposes only the sign-in mode, public Google client ID,
and configuration readiness. `GET /api/v1/auth/me` validates credentials and
returns the authorized administrator's identity and credential expiry.

Extension sync requires:

```text
X-Extension-Token: <DEV_EXTENSION_TOKEN>
```

## Data model

`users`
- Workspace/profile email
- display name
- first/last seen timestamps

`devices`
- stable extension-generated device ID
- owning user
- browser/device label
- extension version
- first/last sync timestamps

`history_visits`
- user/device
- URL/domain/title
- visit time
- Chrome history/visit IDs
- transition
- referring visit ID
- local/synced origin flag
- URL-level visit and typed counts
- receive timestamp

## Important implementation notes

Chrome's `history.search()` returns URL-level history items, while
`history.getVisits()` returns the individual visits. The extension uses both so
the server stores individual browsing events.

This first version creates tables automatically at startup. Before production,
add Alembic migrations.

## Future work

1. Additional investigator/auditor permission levels.
2. Hardware-backed enterprise device attestation.
3. Roles: Administrator, Investigator, Auditor.
4. External audit-log archival and tamper detection.
5. Audit-log retention and archival policies.
6. Production Nginx configuration and HTTPS.
7. Wire the included managed-extension policy schema into Chrome Enterprise deployment.


## Dashboard navigation

- **Overview** (`/`): existing totals and history search by URL, title, domain or
  email, with user and partial-domain filters. History now has Previous/Next
  pagination (100 rows per page). Refresh preserves applied filters.
- **Users** (`/users`): search email/display name, see device count, stored visit
  count and latest successful device sync. Click a user to open `/users/:userId`
  and search their history. Users without devices/visits remain visible with zero
  counts and “Never synced”.
- **Domains** (`/domains`): search domain names and filter by user and local
  date/time range. Results show visits, distinct users and first/last activity,
  ordered by visits descending then domain. Click a domain to open its exact
  matching history, retaining user and time filters. Subdomains remain separate.
- **Reports** (`/reports`): local date-range summaries, optional user/domain filters,
  top 20 domains, visits by day/hour, and CSV export of matching visit rows.
- **Audit Log** (`/audit`): authenticated administrator activity with administrator,
  action and local date/time filters, request details and older-event pagination.
- **Time Spent** (`/time`): measured active time by page, domain and user.
- **Settings** (`/settings`): retention, device health, weekly schedules and public-IP collection rules.

Filters and pagination live in the URL, supporting direct links, reload and
browser Back/Forward. Vite serves nested routes during development. A future
production web server must serve `index.html` for unknown frontend paths.
Dashboard authentication applies to every page and export. Extension sync is unchanged.

Counts are computed in PostgreSQL across matching stored visit rows, **not** by
summing Chrome's URL-level `visit_count` metadata or counting a downloaded page.
User counts cover all time; last sync is the latest `devices.last_sync_at`,
including syncs with no new visits. Domain counts and first/last timestamps
reflect all active filters. Empty hostnames are excluded from domain summaries,
consistent with Overview. Domain/user searches treat `%` and `_` literally.
Time boundaries are inclusive and the UI converts local times to ISO UTC.
Summary endpoints default to 100 rows, accept limits 1–1000 and nonnegative
offsets. History retains its API default of 250 rows. A full final page may
require one additional Next click to discover the end of results.

## Development checks

Frontend (Node 22 or later):

```bash
cd frontend
npm ci
npm run build
```

Backend integration tests use actual PostgreSQL and FastAPI's test client.
**Use an empty disposable database named `milestone_test`**: the tests create
and remove tables, and refuse other database names. Never point them at the
application database.

```bash
cd backend
python -m pip install -r requirements-dev.txt
export DATABASE_URL='postgresql+psycopg://postgres:YOUR_TEST_PASSWORD@localhost:5432/milestone_test'
export AUTH_MODE='development'
export DEV_ADMIN_TOKEN='test-admin'
export DEV_EXTENSION_TOKEN='test-extension'
python -m unittest discover -s tests -v
python -m compileall -q app
```

Tests cover independent user/device aggregation, empty users, last sync, domain
counts and distinct users, first/last activity, exact versus partial-domain
history, search and date filters, pagination, authentication and validation.
The backend creates the new `audit_events` table and its indexes automatically
on startup, using the existing table-creation mechanism. Existing tables and
stored history are preserved. Rebuild the Docker stack with `docker compose up --build -d` to run changes.


## Reports

Reports default to the last seven browser-local calendar days, including today. Select
inclusive `start` and `end` dates (`YYYY-MM-DD`), optionally a `user_id` and a
case-insensitive `domain` substring. The browser sends its IANA `timezone`
(e.g. `America/Chicago`); API callers default to UTC when it is omitted. Both report endpoints require the existing
`X-Admin-Token` header and accept exactly the same filters. Dates are required
and ranges must contain 1–366 days. Domain search treats `%` and `_` literally.
For example:

```text
/api/v1/reports?start=2026-09-01&end=2026-09-16&domain=example.com
/api/v1/reports/export.csv?start=2026-09-01&end=2026-09-16&domain=example.com
```

Summary totals count stored visits and distinct active users/devices/domains
within the filters. Empty hostnames contribute to visits/users/devices but not
the domain count or top-domain list. The top 20 domains sort by visits descending
then domain name. Daily activity includes zero-visit days; hourly activity has
24 local hour-of-day buckets combined across the selected days. Date boundaries
are converted to UTC for querying; storage remains UTC. Daylight-saving days
can contain 23 or 25 hours: skipped hours have zero visits and repeated hours
combine in the same bucket. Invalid timezone names return 422.

CSV export contains all matching individual visits, without the history API's
page limit or the top-domain limit. Columns are visit ID, UTC visit timestamp, local timestamp with UTC offset,
IANA timezone, user email, device name, domain, URL, title and transition. The backend streams
rows in batches; the browser receives the completed download as a file. Very
large exports therefore still need browser memory. Export uses the last applied
filters, not unsaved edits. Navigating away or changing applied filters cancels
an in-progress download. New syncs between generating and exporting a report
may add matching rows; reports are live queries, not saved snapshots.

CSV uses standard quoting for commas, quotes and newlines. Potential spreadsheet
formulas are prefixed with an apostrophe in exported text cells. An empty result
exports column headings only. Tests cover UTC/local boundaries, daylight-saving transitions, fractional offsets, zero buckets, matching
report/export filters, CSV escaping, unauthorized requests, invalid ranges and
exports exceeding 1,000 rows.


History, user sync timestamps and domain activity already render in the browser's
local timezone. Overview's “Visits today” now also uses the browser's local day
(via the optional `timezone` query parameter). Report dates and charts show the
browser timezone explicitly. CSV includes both local time and the original UTC
instant so repeated daylight-saving hours remain distinguishable. No stored
values or schema changes are needed. A shared report URL is interpreted in the
viewer's browser timezone.


Reports also include **Top pages**: up to 20 title/URL combinations with visit
and distinct-user counts, using the same date, timezone, user and domain filters.
The title appears first, with the URL underneath. Missing or whitespace-only
titles appear as “Untitled page”. Identical titles on different URLs remain
separate; changed titles on the same URL also remain separate. Counts sort by
visits descending, then URL and title. CSV exports already include each visit's
original title and URL and continue to export all matching visits.


## Google Workspace sign-in setup

Each school uses its own deployment, database, Google web client and configuration.
The administrator list is a deployment setting, not a hard-coded school/account.
This is not a shared multi-school tenant system: every allowed administrator can
read all history in that deployment. Adding multiple Workspace domains grants
those approved administrators access to the same deployment's data.

1. In the school's Google Cloud project, configure the OAuth consent screen /
   Google Auth Platform branding and audience. Use an Internal audience when
   appropriate for a single Workspace organization.
2. Create an OAuth client of type **Web application**. Add the dashboard's exact
   origin to **Authorized JavaScript origins**, for example `http://localhost:5173`
   for this development stack (also add `http://localhost` for local testing per
   Google's setup guidance), or the school's HTTPS dashboard origin. Scheme,
   hostname and port must match. `localhost` and `127.0.0.1` are different origins.
   This app uses Google's JavaScript popup callback; it does not require a backend
   OAuth redirect endpoint or a client secret.
3. Set these values in the deployment's untracked `.env`:

   ```dotenv
   AUTH_MODE=google
   GOOGLE_CLIENT_ID=YOUR_WEB_CLIENT_ID.apps.googleusercontent.com
   GOOGLE_WORKSPACE_DOMAINS=school.example
   ADMIN_EMAILS=administrator@school.example
   CORS_ORIGINS=http://localhost:5173
   ```

   Use comma-separated domains/emails for additional authorized domains or
   administrators. Matching is exact and case-insensitive, with no wildcards.
   A user must have a verified email, a Google `hd` claim matching a configured
   Workspace domain, **and** an email matching `ADMIN_EMAILS`. An email suffix
   alone is not sufficient. Do not put the admin list or any tokens in frontend
   `VITE_*` variables; the frontend fetches only the public auth configuration.
4. Recreate the stack: `docker compose up --build -d`. Confirm the Google button
   appears, sign in as an allowed administrator and verify the signed-in email
   in the sidebar. A non-allowlisted account must be denied. Direct API calls
   using the development token must also be denied in Google mode.

To add/remove administrators, edit `ADMIN_EMAILS` and recreate the backend with
`docker compose up -d --force-recreate backend`. Authorization is checked on each
API request; an already-open dashboard also revalidates on window focus and every
five minutes. Domain or allowlist changes do not require code edits, frontend
rebuilds or database migrations. Administrator access remains environment-configured;
the Settings page controls collection and retention, not administrator enrollment.

The backend validates the signature, issuer, audience and expiry using Google's
Python authentication library; it caches public signing certificates according
to Google's cache headers. Missing configuration, unverified accounts, unknown
domains, non-allowlisted emails and verification failures deny access. Network
verification outages return a retryable error without enabling development auth.

The browser keeps the credential in tab session storage (not persistent local
storage), validates it with `/auth/me` before opening protected pages, and sends
it only in an authentication header. Legacy development tokens are removed from
local storage and migrated only after successful development-mode validation.
On token expiry or authorization denial, the dashboard returns to sign-in.
Sign out clears the app's tab credential; it does not sign out of Google or revoke
an already-issued Google ID token on other devices. There is no refresh-token
storage or offline access. Sign-in must be repeated after the Google ID token
expires. HTTPS is required outside localhost, and scripts on the dashboard
origin must be trusted because session storage is accessible to same-origin JS.

The app uses the GIS **JavaScript callback** flow with explicit bearer headers,
not a cookie-authenticated login POST. It sets no ambient authentication cookies.
If a future change introduces cookie sessions or Google's redirect POST flow,
implement the corresponding CSRF/state protections for that flow.

Automated auth tests use locally signed JWTs and mocked public signing keys to
exercise the real Google verification library, including bad signatures, audience,
issuer and expiry, domain/email restrictions, mode isolation, outage handling and
CORS. Live Google account sign-in must additionally be checked with the school's
registered OAuth client; it cannot be validated with placeholder client settings.

Reference: [Google sign-in setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid),
[server-side ID token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).


## Audit log

The backend records authenticated API access to Overview, user lists/details,
domain summaries, history views/searches, reports, CSV exports and the audit log
itself. It captures the verified Google subject/email (or the clearly labeled
shared development identity), UTC timestamp, action, HTTP status, supported
explicit filters and result count where available. No authentication headers,
tokens, returned page titles, response bodies or browsing rows are copied into
the audit log. Search text and target IDs **are** recorded as filters and may
contain sensitive investigation context. Values over 4,096 characters are
shortened and marked. Unknown query parameters are excluded.

Records describe API requests, not proof that a person read the response. A page
can produce several records for supporting requests such as user dropdowns;
refreshes, retries and React development-mode requests can each create records.
Successful responses are labeled Accepted. Authenticated validation/query errors
are recorded with their HTTP status. Requests that fail authentication are not
attributed to an administrator; anonymous login-attempt monitoring is outside
this milestone. `/auth/me`, public auth configuration, health checks and extension
sync are not included in this administrator-access log.

`export.requested` is saved **before any CSV bytes are released**. It records an
authorized export request, not completion, a saved file, a row count or receipt
by a user. A later streaming error or disconnected browser does not turn it into
a completed export event. Other result counts refer to rows returned, or matching
visit counts for reports, and are not snapshots of the returned content.

Audit writes use a separate database transaction. If a record cannot be saved,
the API returns 503 rather than releasing unaudited data. The application exposes
no audit edit/delete endpoints and records do not depend on monitored user/device
foreign keys. This is append-only **through the application**, not a tamper-proof
ledger: database owners can still modify the table. Audit retention and external
archival remain future work. All currently allowlisted administrators may read
this deployment's audit log.

`GET /api/v1/audit` supports `actor` (email or subject substring), `action`,
inclusive `start`/`end` timestamps, `before_id`, and `limit` (1–200, default 100).
The UI converts browser-local time filters to UTC. The API returns `items` and
`next_cursor`; pass that value as `before_id` to get older events. New inserts,
including viewing the audit log itself, do not shift older-page boundaries.
The current read event appears on a later refresh. Use Latest events to restart
or browser Back to return to a previous page. Audit timestamps display locally.

Tests cover authenticated identity, filter/credential separation, report/export
recording, failed queries, database-write failure, access protection, local time
filter conversion and pagination while new records are inserted.

## Active browsing time

The **Time Spent** page shows measured time grouped by page (title and URL),
domain, or user. It defaults to all users and all collected time. Select a user
for individual page/domain totals; filter by domain, search text, or local date
and time. User history includes a link to that user's time breakdown. Reports
include the same breakdown within their selected local date range. Existing
history CSV exports remain visit records; they do not invent per-visit durations.

To enable collection, rebuild the backend/frontend (`docker compose up --build -d`)
and reload or redeploy extension version **0.3.0** (active time was introduced in 0.2.0). The extension now requires
Chrome 120+ and the `tabs` and `idle` permissions. The backend creates the new
`activity_intervals` table on startup; existing history remains intact. Collection
starts with the updated extension: older visits cannot be backfilled with time.

Time means estimated active time in the HTTP(S) tab of a focused normal Chrome
window. It pauses when Chrome loses focus, the system locks, or Chrome reports
60 seconds of system inactivity. Incognito and internal browser pages are
excluded. Passive reading after the idle threshold is not counted. Totals sum
across devices and are not a measurement of attention or unique human wall time.

The extension samples every 30 seconds and at tab/focus/idle transitions. Gaps
longer than 45 seconds are discarded conservatively, including delayed alarms
and sleep gaps. Worker checkpoints and queued samples are persisted together;
browser restarts reset the checkpoint. Crashes, delayed events, and missing
samples can undercount. See Chrome's [alarm behavior](https://developer.chrome.com/docs/extensions/reference/api/alarms),
[idle API](https://developer.chrome.com/docs/extensions/reference/api/idle), and
[service worker lifecycle](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle).

Queued samples retain stable IDs so retries cannot double count. The local queue
is bounded at 10,000 samples / approximately 4 MB; new samples are skipped when
full. Extension Options shows the last activity sync and error. Queues are bound
to the original server, email, and device; changing configuration never reassigns
old samples to another user. Unsent samples for an old configuration remain local
until that configuration is restored (and still count toward the queue limit).

`POST /api/v1/sync/activity` uses the configured extension authentication mode:
a bound device credential in enrolled mode, or the shared token in development
mode. It accepts up to 250 timestamped samples per batch, requires aware
UTC-compatible timestamps and positive intervals of at most 90 seconds, rejects
overlapping intervals on one device, and acknowledges retries idempotently.
Only enrolled mode verifies the Google identity and binds uploads to that user
and device. The development token does not verify the reported user's identity.

`GET /api/v1/activity/summary` requires administrator authentication and is
recorded as `activity.view` in the audit log. Parameters: `group_by`
(`page`, `domain`, `user`), optional `user_id`, literal substring `domain`/`q`,
aware `start` and exclusive `end`, `limit` (1–200, default 100), and `offset`.
PostgreSQL calculates totals and clips intervals to the requested boundaries.
Timestamps stay in UTC; display and date selection use the browser timezone.

Validation includes PostgreSQL aggregation, clipping, user isolation, retries,
overlap rejection and authentication, plus extension simulations for focus,
idle, restart, offline retry and excluded pages. Run the extension checks with
`node --test extension/tests/activity.test.cjs`.

## Settings: retention, health and collection rules (extension 0.3.0)

Rebuild with `docker compose up --build -d`, reload/redeploy the extension, and
accept its additional `https://api64.ipify.org/*` host permission. Two new tables
(`collection_settings`, `device_health`) are created on backend startup without
changing existing history. No rules or deletion are enabled automatically:
retention defaults to indefinite, schedule and IP restrictions default to off,
the school timezone defaults to `America/Chicago`, and the stale check-in
threshold defaults to 15 minutes. Existing administrator authentication is unchanged.

The **Settings** page saves one deployment-wide policy shared by all users.
Changes are revision checked to avoid overwriting another administrator's edit.
The edit and its audit record (before/after policy, with no signing key) commit
in one transaction. All currently allowed administrators can edit these settings.

### Retention

Set 1–3,650 days, or leave blank for indefinite storage. Saving a number enables
**permanent deletion**, including already stored records older than that period.
The backend runs cleanup at startup and every five minutes, deleting up to 10,000
old history rows and 10,000 expired activity intervals per pass. Larger backlogs
therefore take multiple passes. Intervals crossing the cutoff have their start
clipped to it. Uploads older than the retention cutoff are filtered out so a
retry/backfill cannot restore expired data. Users, devices, and audit records
remain. The worker is part of the backend process; it resumes after downtime.
Database failures are logged and retried on the next pass. Database backups and
browser-local Chrome history are not deleted by this policy.

### Weekly schedule

Enable scheduling and choose a start/end for each day (Monday through Sunday).
Unchecked days have no window starting on that day. An enabled schedule with no
enabled days pauses all collection. An end earlier than its start means overnight:
Friday 22:00–02:00 includes early Saturday even if Saturday has no own window.
Equal start/end times are rejected. Start is inclusive; end is exclusive.
Disable scheduling for unrestricted hours.

Rules use the configured IANA school timezone and honor daylight saving changes,
independent of the device's timezone. Repeated fall-back hours follow the same
wall-clock rule; nonexistent spring-forward hours contain no instants to collect.
Stored timestamps remain UTC; ordinary dashboard/report timestamps still use the
administrator's local browser timezone.

### Public-IP allowlist: public servers and LAN/localhost

Enable the IP rule and enter individual public IPv4/IPv6 addresses, one per line.
An empty enabled list blocks collection. Private/reserved addresses and CIDR
ranges are rejected. The address is the school's public egress address, not a
Chromebook's private Wi-Fi address. If a school uses multiple egress or IPv6
addresses, list those as well. When schedule and IP rules are enabled, **both**
must allow collection.

Two explicitly selectable detection modes are available:

- **Backend connection** (default): uses the request's TCP peer address. For a
  trusted reverse proxy, set `TRUSTED_PROXY_CIDRS` to its exact addresses/networks
  and configure that proxy to replace or safely append `X-Forwarded-For`. The
  application walks the chain from the trusted end and stops at the first
  untrusted address. Headers from untrusted peers are ignored. The Docker command
  disables Uvicorn's own proxy-header rewriting; preserve `--no-proxy-headers`
  when launching outside Docker so the application can validate the actual peer.
  Do not trust all networks. A private Docker/LAN peer cannot match a public-IP
  allowlist: use the device-lookup mode for that topology unless a correctly
  configured trusted proxy conveys the real source address.
- **Device lookup**: suitable when the backend is on localhost or the school LAN.
  The extension requests `https://api64.ipify.org?format=json` over HTTPS, with no
  browsing data, user identity or extension credentials attached, and sends the
  returned address to the backend policy endpoint. This exposes the ordinary
  connection IP to that third-party service. Lookup failure pauses collection.
  This mode relies on the managed extension reporting honestly; it is not a
  server-verified network-location guarantee. The [ipify API documentation](https://www.ipify.org/)
  describes its dual-stack endpoint. IPv4/IPv6, VPN and split-routing choices can
  produce different egress addresses for different destinations; use the observed
  device address in Collection health when configuring the list.

The extension still needs a host permission for its backend origin. For another
school hostname or a LAN address, update `extension/manifest.json`'s backend
`host_permissions` before deploying; changing API URL alone cannot grant access.
No live school IPs are assumed or enabled by this change.

### Enforcement, timing and backfill

The extension checks policy before reading history or measuring time, and checks
in normally every 30 seconds even while collection is paused. Successful policy
checks can be cached for 20 seconds. When permitted, the server issues a signed
permission valid for at most 45 seconds, shortened at schedule boundaries and
bound to policy revision, user and device. Restricted uploads require this
collection-time permission on each visit/interval. Their timestamps must lie
within its bounds. A later approved network connection cannot authorize past
unverified browsing. The backend independently filters noncompliant uploads,
including uploads from older extension versions that ignore the policy.

Network location is sampled, not continuously attested. A network switch may
remain undetected until the next check; permissions last at most 45 seconds.
Browser sleep/delayed alarms can delay checks, but cannot extend a permission.
Keep device/server clocks synchronized; bad clocks can cause conservative drops.
Development mode still uses a shared credential and unverified profile identity.
Enrolled mode verifies the Google profile; neither mode provides tamper-proof
device attestation.

Restricted collection disables arbitrary initial/history backfill. Reconciliation
only uses visits covered by recent permissions in the current browser session
(up to 20 minutes retained locally). Policy/API failures pause new collection;
already measured, permitted activity can retry later. Saving settings invalidates
all earlier permissions; queued old-revision samples are acknowledged as filtered
and discarded rather than retrying forever. Activity intervals crossing a permission
boundary are clipped or conservatively skipped. No durations are inferred across
missing samples. Unrestricted settings preserve the original historical backfill.

Health check-ins contain enrollment identity, extension version, observed IP and
collection status even outside collection hours. They contain no visited URLs or
page titles. Collection health distinguishes ready, schedule-paused, IP-paused,
unavailable public IP, stale check-in, and devices needing the updated extension.
Ready is not proof of browsing; sleeping/closed browsers eventually look stale.
Last sync means an acknowledged upload, which may contain only duplicates or
filtered records. Refresh the dashboard to update health. Extension Options shows
collection status, public IP, last policy check and sync errors.

### Endpoints and verification

- `GET /api/v1/settings`: current policy and revision (administrator; audited).
- `POST /api/v1/settings`: validated complete policy plus expected revision
  (administrator; atomic settings/audit write; 409 for a stale revision).
- `GET /api/v1/settings/devices`: paginated health, with `q`, `offset`, `limit`
  (administrator; audited).
- `POST /api/v1/sync/policy`: enrollment metadata and optional `public_ip` in
  device-lookup mode (extension credential); returns reason and collection permission.
- Existing sync endpoints accept optional `collection_permit` per record and
  return a `filtered` count when records are excluded.

Automated backend tests exercise schedule boundaries/overnights/DST, IP modes and
proxy spoofing, signed permission scope/tampering, both upload paths, retention
and audit transaction behavior. Extension tests cover history gating and backfill,
permission expiry, policy failure, lookup isolation, and activity retry behavior:
`node --test extension/tests/*.test.cjs`.


## Automatic managed enrollment (0.4.0)

Extension 0.4.0 adds a non-interactive Google enrollment path, per-profile device
credentials, renewal, and administrator revocation. Google Admin supplies the
server URL and managed options; there are no enrollment codes to distribute.
The backend adds `device_enrollments` automatically on startup. Local testing
continues in development mode until explicitly configured otherwise.

Start with [the managed deployment guide](docs/managed-deployment.md) and its
[Google Admin policy example](docs/google-admin-policy.example.json). The package
builder (`scripts/package_extension.py`) supports an initial store draft and a
release with the publisher's real Chrome Extension OAuth client ID. A stable
store ID and OAuth client have not yet been configured in this testing setup.
Force-installation alone does not guarantee silent Google authorization; the
fresh-profile pilot on all three platforms is a rollout gate, not an optional
manual-enrollment step for users.

## GitHub-hosted extension releases

For the same GitHub Actions + Releases + Pages deployment model as the Eaglercraft
blocker, use [GitHub deployment](docs/github-deployment.md). This provides signed
CRX3 packages and a stable update feed for managed force installation without a
Web Store listing. Backend hosting and verified Google enrollment are still required.
