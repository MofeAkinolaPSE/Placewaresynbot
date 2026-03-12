# Supabase Migration Notes (PlacewareBot)

This guide summarizes the schema, extensions, and RPC needed for PlacewareBot.

## Prereqs
- Enable `pgvector`:
  ```sql
  create extension if not exists vector;
  ```
- Ensure your service role key is used for migrations; runtime can use anon or service depending on policy.

## Core Tables
- Leads: `placeware_leads`
- Audit logs: `placeware_audit_logs`
- Stock cache: `placeware_stock_cache`
- RAG vectors: `qna` (columns: `question text`, `answer text`, `embedding vector(384)`)
- Sage snapshots (append-only):
  - `sage_customers_snapshot`
  - `sage_ar_snapshot`
  - `sage_ap_snapshot`
  - `sage_gl_snapshot`
  - `sage_inventory_snapshot`
- Workflow:
  - `placeware_intents`
  - `placeware_approvals`

Apply migrations in this repo:
- `backend/migrations/002_sage_snapshot_tables.sql`
- `backend/migrations/003_workflow_tables.sql`
- `backend/migrations/021_order_workflow_enrichment.sql` (lead-to-order linkage)

## RPC: match_documents
`/chat` uses a Supabase RPC to retrieve semantically similar Q&A rows.

Contract:
- Signature: `match_documents(query_embedding vector, match_threshold float, match_count int)`
- Returns: rows with `question`, `answer` and optionally `score`.

Example implementation (adjust schema names as needed):
```sql
create or replace function public.match_documents(
  query_embedding vector,
  match_threshold float,
  match_count int
)
returns table (
  question text,
  answer text,
  score float
) language sql stable as $$
  select q.question, q.answer,
         1 - (q.embedding <=> query_embedding) as score
  from public.qna q
  where 1 - (q.embedding <=> query_embedding) >= match_threshold
  order by q.embedding <=> query_embedding asc
  limit match_count;
$$;
```

## Policies (simplified)
- For write paths used by backend service key, you can skip RLS or use permissive policies for service role.
- For anon reads (e.g., stock cache), use RLS with `select` allowed if public.

## Seeding Q&A
- Ensure `qna.embedding` type is `vector(384)`.
- Use `backend/src/seed_qna.py` to insert rows from `data/qna_pairs_with_embeddings.csv`.

## Env & Configuration

Use `DATABASE_URL` for direct Postgres connections when running against Postgres (local or managed). Only set
`SUPABASE_URL`/`SUPABASE_KEY` if you plan to use a hosted Supabase project with its REST/Auth APIs.

`.env` / `.env.example` keys (recommended):
- `DATABASE_URL` (preferred for direct Postgres access)
- `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`
- Optional: `JWT_SECRET`, `RATE_LIMIT`, `DEV_TOKEN_ENABLED`

## Verification Checklist
- [ ] `vector` extension installed
- [ ] `qna.embedding` is `vector(384)`
- [ ] `match_documents` RPC returns expected rows
- [ ] Migrations 002 and 003 applied
- [ ] Migration 021 applied (or equivalent fields present in bootstrap schema)
- [ ] `placeware_orders` has `source` and `lead_id` columns
- [ ] Backend can insert snapshots and intents (service key)
