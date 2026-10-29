---
paths:
  - "backend/**"
---
# Backend

Use existing route, schema, dependency, and SQLAlchemy patterns. Preserve admin
authentication, extension credential checks, and audit coverage when adding routes.
Dashboard OAuth and extension OAuth are different clients and allowlists.
In enrolled mode, bind every upload/policy request to the credential's user and device.
Never silently downgrade failed enrollment to a shared development token.

Keep datetimes timezone-aware. Preserve exclusive upper bounds and timezone-aware
report date filtering. Maintain idempotent history/activity retries and reject
invalid or overlapping active intervals. Enforce collection policy server-side.
Treat IP claims according to their configured source; never trust arbitrary
X-Forwarded-For headers. Avoid recording raw credentials, URLs containing tokens,
or complete request bodies in logs/audit details.

Startup uses `Base.metadata.create_all`; this does not migrate existing columns.
Plan explicit backward-compatible migration and recovery steps for schema changes.
Retention runs inside the backend. Do not scale replicas without reviewing startup
and maintenance concurrency. Do not execute cleanup against production while testing.

## Tests

Provision a separate empty PostgreSQL database named `milestone_test`. Tests can
create/drop tables. Use a separate database server/container when practical, and
never select a database based only on its name without verifying its host.

From `backend/`, in a development virtual environment:

```sh
python -m pip install -r requirements-dev.txt
export DATABASE_URL='postgresql+psycopg://postgres:TEST_PASSWORD@localhost:5432/milestone_test'
export AUTH_MODE=development
export EXTENSION_AUTH_MODE=development
export DEV_ADMIN_TOKEN=test-admin
export DEV_EXTENSION_TOKEN=test-extension
python -m unittest discover -s tests -v
python -m compileall -q app
```

Replace the placeholder password/host with those of the disposable database.
Use actual PostgreSQL for database integration checks; SQLite does not exercise
PostgreSQL-specific types, locking, constraints, or aggregation behavior.
