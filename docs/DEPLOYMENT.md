# Deployment: local development vs. SAP BTP + Supabase

SIGAP runs on **one PostgreSQL database** (application + chatbot). There are two environments, selected by `APP_ENV`:

| | Development (`APP_ENV=development`, default) | Production (`APP_ENV=production`) |
|:--|:--|:--|
| Where | your machine, `docker compose up` (or `uvicorn` on the host) | SAP BTP Cloud Foundry (`manifest.yml`) |
| Database | Postgres **17** container `db` (port 5433): DB `mrp`, test DB `mrp_test` | Supabase (Postgres 17.x), transaction pooler port 6543 |
| Credentials | `backend/.env` (git-ignored) | `deploy/vars.yml` (git-ignored) → `cf push --vars-file` |
| Safety | the app **refuses to start** with a `*.supabase.com` / `*.supabase.co` `DATABASE_URL`; `pytest` refuses Supabase URLs too | — |

Local code therefore never touches Supabase. The local database has the same major version as Supabase and the same schema, because both are created from the same SQLAlchemy models (`create_all`) plus the idempotent column migrations in `backend/app/db_migrate.py`, which run on every backend start.

## Local development

```bash
cp backend/.env.example backend/.env        # APP_ENV=development, DATABASE_URL=…localhost:5433/mrp, AICORE_*
docker compose up --build                   # db (Postgres 17) + backend + supplier-worker + frontend
docker compose exec backend pytest -q       # tests on mrp_test (never Supabase)
```

The Postgres volume is named `db-data-pg17`. The volume of the old Postgres 16 setup (`sigap-mrp_db-data`) is no longer used and can be removed with `docker volume rm sigap-mrp_db-data`.

## Production: SAP BTP Cloud Foundry + Supabase

1. **Credentials.** Copy `deploy/vars.example.yml` to `deploy/vars.yml` (git-ignored) and fill in:
   - `database_url`: Supabase → *Connect* → **Transaction pooler** (`…pooler.supabase.com:6543/postgres`). The app only uses transaction-scoped settings (`SET TRANSACTION READ ONLY`, `SET LOCAL statement_timeout`) and psycopg2 does not use server-side prepared statements, so the transaction pooler is safe.
   - `backend_host` / `frontend_host`: fixed route hostnames on `cfapps.ap10.hana.ondemand.com` (defaults `mrp-backend-suppliers` / `mrp-frontend-suppliers`; change them if another team already uses them).
   - `cors_origins`: exactly the frontend URL, `https://<frontend_host>.cfapps.ap10.hana.ondemand.com` (no trailing slash; comma-separate several). The backend only accepts browser requests from these origins.
   - `aicore_*`: SAP AI Core keybroker values.
   - `telegram_*`: bot token, bot username, manager chat id, `telegram_mode: telegram`.
2. **Push.**

   ```bash
   cf login -a <api-endpoint>
   cf push --vars-file deploy/vars.yml
   ```

   `manifest.yml` deploys three apps:
   - `mrp-backend-suppliers` (API; creates missing tables and applies `db_migrate` on start),
   - `mrp-supplier-worker` (no route, process health check, **exactly one instance**: Telegram long polling, conversation dispatch, Hub missions, reminders),
   - `mrp-frontend-suppliers` (static build; build it first with `VITE_API_URL=https://<backend_host>.cfapps.ap10.hana.ondemand.com/api/v1 npm run build`).
3. **Data.** The Supabase database already contains the schema and master data. New columns are added automatically at startup. Demo data is opt-in only: `APP_ENV=production DATABASE_URL=<supabase> python -m scripts.seed` (never with `--reset` on production).

## Secrets

- Never commit credentials. `backend/.env`, `deploy/vars.yml` and the root `.env` are git-ignored; `backend/.env.example` and `deploy/vars.example.yml` contain placeholders only.
- An earlier version of `backend/.env.example` contained a real Supabase password and SAP AI Core client secret. They remain in the git history: **rotate both** (Supabase → Database → Reset password; SAP BTP → AI Core service key → recreate) and update `deploy/vars.yml` / `backend/.env`.

## Performance on SAP BTP

Every SQL statement is a network round trip from Cloud Foundry (`ap10`, Sydney) to Supabase. Measured between Sydney and a Supabase project in Seoul (`ap-northeast-2`) that is about **140 ms per statement**, so a page that runs one query per supplier gets slow fast (36 suppliers × 5 queries ≈ 25 s).

What the code does about it:
- **Fixed query count per page.** Hub status, suppliers (Telegram links), conversations, missions, approvals, purchase orders and the activity log load related rows in batches (`IN (…)`, window functions, `selectinload`), never per row. `backend/tests/test_query_budget.py` fails if a list endpoint's query count grows with the number of rows.
- **No overlapping polls.** The frontend skips a poll while the previous request is still running; the global Hub badge polls every 30 s.
- **Tracing off the request path.** `agent_runs` / `tool_runs` are written by a background thread (`AGENT_TRACE_ASYNC=true`, the default).
- **Transaction pooler safe.** The chatbot checkpointer never uses server-side prepared statements (`prepare_threshold=None`).

What only the cloud setup can fix: the per-statement distance. Create the Supabase project in **`ap-southeast-2` (Sydney)**, the same region as CF `ap10`. That brings a round trip down to a few ms. Supabase cannot move an existing project between regions, so this means a new project plus a dump/restore (`pg_dump` → `psql`) and a new `database_url` in `deploy/vars.yml`.
