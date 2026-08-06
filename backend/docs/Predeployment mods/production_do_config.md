# Production DigitalOcean DB Configuration (quick start)

Purpose: guidance for running PlacewareBot with a DigitalOcean Managed PostgreSQL instance.

1) Decision: Supabase vs Direct Postgres
- If you plan to keep Supabase for runtime (recommended minimal change), set `SUPABASE_URL` and `SUPABASE_KEY` in your env.
- If you migrate to DO Managed Postgres, set `DATABASE_URL` and update `src/db.py` to use a direct DB client (psycopg2/SQLAlchemy) and run migrations.

2) Minimal env vars (see `.env.example`)
- `DATABASE_URL` with `?sslmode=require` for DO Managed Postgres.
- `JWT_SECRET`, `WEBHOOK_SECRET`, `DEEPSEEK_API_KEY`, and `EMAIL_*` credentials.

3) Secure Networking
- Use a VPC/private networking between Droplet and Managed DB.
- Restrict DB to droplet's IP or VPC; never expose DB publically.

4) Backups & Migrations
- Enable automated backups in DO Managed Postgres.
- Run SQL migrations from `backend/migrations/` in order on staging before prod.

5) Systemd + env file
- Place env at `/etc/placewarebot/backend.env` with 600 permissions.
- Example systemd unit in `backend/docs/deployment_runbook_do.md`.

6) Monitoring & Alerts
- Configure DO Insights and Uptime checks for health endpoints (`GET /`).

7) Rollout checklist
- Test full import flow with `POST /import` in staging.
- Validate agent triggers and workflow executions.
