# Production DB Strategy

Purpose: outline recommended production database strategies and migration steps for Placeware.

Options considered

- Supabase (managed PostgreSQL + auth + storage + edge functions)
  - Pros: integrated auth, row-level security, RPC functions (pgvector), easy for current code which uses Supabase SDK.
  - Cons: vendor lock-in for auth and SDK patterns; migration to plain Postgres requires SQL migration of RLS policies.

- Managed PostgreSQL (DigitalOcean / AWS RDS / Azure DB)
  - Pros: standard Postgres with full control, compatible with DO managed offering.
  - Cons: need to reimplement Supabase features (auth, storage) or use separate services.

Recommendation

1. Continue with Supabase for short-term production (quicker to deploy, current code uses Supabase SDK).
2. Prepare a migration plan to move to standard managed PostgreSQL if required for cost/control:
   - Export all SQL migrations (already present in `backend/migrations/`).
   - Create a compatibility layer for auth (use JWT middleware mapping to `placeware_users`).
   - Replace Supabase SDK calls with a lightweight DB adapter using `asyncpg` or `psycopg`.

Operational notes

- Run migrations in staging first; validate indexes and RLS policies.
- Ensure `AT_REST_KEY` and `WEBHOOK_SECRET` are provisioned in environment.
- Set up connection pooling and monitor `max_connections` in managed DB.

Rollback plan

- Maintain a snapshot/backup schedule.
- Use transactional migration patterns and avoid destructive changes without backups.

*** End of document
