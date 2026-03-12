Backend notes — CRM & Agents (Section C)

Quick start (local dev):

- Copy `.env.example` to `.env` and populate required values (DATABASE_URL, JWT keys, LLM keys etc.).
- Install dependencies: `pip install -r requirements.txt`.
- Apply migrations against your Postgres instance in order (use `backend/migrations`).
- Start app: `uvicorn app:app --reload` (run from the `backend` folder).

Dockerized local Postgres (recommended for dev)

1. Bring up Postgres (docker-compose):

```bash
cd backend
docker compose up -d
```

2. Set `DATABASE_URL` (example):

```bash
export DATABASE_URL=postgresql://placeware:placeware@localhost:5432/placeware_dev
```

3. Install migration dependency and apply migrations:

```bash
cd backend
pip install -r requirements.txt
pip install psycopg2-binary
python scripts/apply_migrations.py
```

4. Start the app:

```bash
uvicorn app:app --reload
```

Notes:
- Use `pgAdmin`, TablePlus, or your cloud provider's DB management UI to administer the database.
- The migration runner applies all SQL files in `backend/migrations` in lexical order; ensure migration files are correct before running in production.
- The migration runner applies all SQL files in `backend/migrations` in lexical order; ensure migration files are correct before running in production.

Running tests (unit):

```
cd backend
pytest -q
```

What these tests do:
- `tests/test_crm_endpoints.py` contains lightweight unit tests that mock the Supabase client and JWT decode helper to validate CRM endpoint wiring (event ledger insertion, lead/opportunity creation flows).

Next recommended steps:
- Add integration tests that run against a real Postgres instance (use docker-compose to spin a test DB).
- Expand test coverage for agents (simulate Postgres NOTIFY) and workflow engine file ingestion.
# Embed-service
System Embeding
