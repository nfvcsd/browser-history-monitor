# Browser History Monitor

## Purpose and architecture

Managed Chrome history and active-time reporting for school administrators.
This is a single-school deployment, not an isolated multi-tenant service.

- `backend/app/`: Python 3.13, FastAPI, SQLAlchemy, PostgreSQL 17; routes under `/api/v1`.
- `frontend/src/`: React, TypeScript, Vite, React Router; npm with a committed lockfile.
- `extension/`: Manifest V3 service worker, managed configuration, collection policy,
  history synchronization, active-time sampling, Google-verified profile enrollment.
- `scripts/`: ZIP packaging and signed self-hosted CRX3 builds.
- `deploy/` and `docs/`: Jamf/Google Admin configuration and deployment runbooks.

Implemented pages include Overview, Users, Domains, Reports, Time Spent, Audit Log,
and Settings. Preserve page-title reporting and browser-local time displays.
Store timestamps in UTC; school collection schedules use their configured timezone.
Perform filtering, aggregation, and pagination in PostgreSQL rather than downloading
all history to the browser. Active time is an estimate, not proof of attention.

## Working conventions

Read the relevant source and runbook before editing. Preserve unrelated user changes.
Keep changes focused and update documentation when behavior or configuration changes.
Leave changes uncommitted for review unless the user explicitly asks for a commit.
Do not push, publish releases, or change deployed services without user authorization.
Do not infer authorization to delete live data from a request to run tests.

Never expose `.env`, `.env.production`, signing keys, tokens, database dumps, or
screenshots of real history in code, logs, commits, or public artifacts. Use synthetic
fixtures. Public OAuth client IDs are identifiers, not private client secrets.
Project instructions guide behavior; they are not a substitute for access controls.

## Development and validation

From the repository root:

```sh
# Extension unit tests
node --test extension/tests/*.test.cjs
# Packaging tests; real Chrome check skips unless Chrome is available
python3 -m unittest discover -s scripts/tests -v
```

Frontend: from `frontend/`, run `npm ci` and `npm run build` (type check + Vite build).
Use Node 22 or later. There is no configured frontend `npm test` script.

Backend: follow `.claude/rules/backend.md`; tests create/drop tables and require an
isolated PostgreSQL database named `milestone_test`. Never use the application DB.
Run checks relevant to the change, report exact results, and distinguish unit tests,
container smoke tests, and live managed-device verification. Do not claim Google
OAuth or fleet rollout success solely from mocks or a successful package build.

## Deployment boundaries

- `docker-compose.yml`: local development, development tokens and Vite server.
- `compose.production.yml`: standalone Ubuntu production configuration. Do not merge
  it with the development file. Google admin auth and enrolled extension auth are required.
- Production topology and startup: `deploy/linux/README.md`.
- Extension distribution and signing: `docs/github-deployment.md`.
- Identity and enrollment limitations: `docs/managed-deployment.md`.
- General behavior and API documentation: `README.md`.

Consult current files for version numbers and environment configuration. The VM
has been reported running, but verify live state when needed rather than treating
these instructions as a health check. Silent enrollment on fresh managed profiles
still needs an actual pilot on each target platform.
