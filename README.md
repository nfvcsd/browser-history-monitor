# Browser History Monitor — Milestone 2

This repository contains the centralized Chrome history system with routed
Overview, Users and Domains pages:

- Chrome Manifest V3 extension
- FastAPI REST API
- PostgreSQL storage
- React + TypeScript dashboard
- Docker Compose development environment

## Security status

This milestone intentionally uses two development tokens:

- `DEV_EXTENSION_TOKEN` authenticates extension sync requests.
- `DEV_ADMIN_TOKEN` authenticates dashboard/API requests.

The extension also reports the Chrome profile email (or a configured fallback).
That identity is **not yet cryptographically verified**. Do not expose this
version to the public Internet as a production monitoring system.

A future milestone should replace development authentication with Google
Workspace OIDC and bind extension enrollment to a verified Workspace identity.

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

5. Paste `DEV_ADMIN_TOKEN` into the dashboard when prompted.

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

Dashboard endpoints require:

```text
X-Admin-Token: <DEV_ADMIN_TOKEN>
```

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

1. Google Workspace OIDC for the React dashboard.
2. Verified extension enrollment instead of a shared sync token.
3. Roles: Administrator, Investigator, Auditor.
4. Audit logging for history access/search/export.
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
- **Reports, Audit Log and Settings** are disabled, clearly labeled placeholders.

Filters and pagination live in the URL, supporting direct links, reload and
browser Back/Forward. Vite serves nested routes during development. A future
production web server must serve `index.html` for unknown frontend paths.
Development token authentication and extension sync are unchanged.

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
export DEV_ADMIN_TOKEN='test-admin'
export DEV_EXTENSION_TOKEN='test-extension'
python -m unittest discover -s tests -v
python -m compileall -q app
```

Tests cover independent user/device aggregation, empty users, last sync, domain
counts and distinct users, first/last activity, exact versus partial-domain
history, search and date filters, pagination, authentication and validation.
No database migration is needed for this milestone; existing tables/indexes are
used. Rebuild the Docker stack with `docker compose up --build -d` to run changes.
