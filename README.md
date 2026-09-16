# Browser History Monitor — Milestone 5

This repository contains the centralized Chrome history system with routed
Overview, Users, Domains and Reports pages:

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

The extension still uses `DEV_EXTENSION_TOKEN` and reports an **unverified**
profile email. Verified extension enrollment, retention and
production deployment hardening remain future work.

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
2. Verified extension enrollment instead of a shared sync token.
3. Roles: Administrator, Investigator, Auditor.
4. External audit-log archival and tamper detection.
5. Configurable retention.
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
- **Settings** is a disabled, clearly labeled placeholder.

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
rebuilds or database migrations. Settings remains a placeholder; there is no
in-app administrator editor in this milestone.

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
