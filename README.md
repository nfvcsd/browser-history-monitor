# Browser History Monitor — Milestone 1

This repository contains the first runnable version of the centralized Chrome
history system:

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

The next milestone should replace development authentication with Google
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
- `GET /api/v1/users`
- `GET /api/v1/history`

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

## Next milestone

1. Google Workspace OIDC for the React dashboard.
2. Verified extension enrollment instead of a shared sync token.
3. Roles: Administrator, Investigator, Auditor.
4. Audit logging for history access/search/export.
5. Configurable retention.
6. Production Nginx configuration and HTTPS.
7. Wire the included managed-extension policy schema into Chrome Enterprise deployment.
