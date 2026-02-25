# Copilot Project Instructions – PlacewareBot (RAG Chat + WP + Supabase)

Purpose: FastAPI RAG backend + (legacy) WordPress plugin + optional Gradio/HF embedding proxy. This doc orients AI agents so they can extend/refactor toward PlacewareBot (pharma domain) while safely replacing legacy PSE / SynBot branding.

## Architecture (Current State)
- Backend (`backend/`): FastAPI app (`app.py`) exposing `/chat`, `/submit_lead`, root health.
- Retrieval: `src/retrieval.py` calls Supabase RPC `match_documents` (expects SQL function + pgvector 384-dim embedding column `embedding`). Similarity threshold hard‑coded (0.78) and top-k adjustable (default 3 in `app.py`).
- LLM: `src/deepseek.py` wrapper around DeepSeek chat completions (model in `DEEPSEEK_MODEL`). System prompt still references old brand (must be swapped to PlacewareBot + pharma disclaimer when domain migration happens).
- Embeddings: Runtime embedding injected by client or fetched via `src/embed_proxy.py` which hits a Gradio Space (`EMBED_URL`). Assumes 384-dim MiniLM-style embedding.
- Lead capture: `src/db.py` inserts into Supabase table named "PSE Leads Table" then emails department (recipients loaded from `config.yaml`). Naming + subject line still branded (needs rename to Placeware).
- WordPress plugin (in `my-plugin(2)/`): registers REST route `psebot/v1` and assets with `psebot_*` prefix. This will need namespace migration to `placewarebot`.
- Data: Pre-embedded CSV `data/qna_pairs_with_embeddings.csv` used to seed Supabase.

## Key Refactor Targets for Domain Switch
- Replace every occurrence of: `PSEBot`, `PSE`, `SynBot`, `psebot` with: `PlacewareBot`, `Placeware`, `placewarebot` (case sensitive variants) excluding historical data provenance if needed.
- Update DeepSeek system instruction to medical/pharma compliance style + add NAFDAC disclaimer tail (central constant to avoid drift).
- Rename Supabase tables (e.g., from `PSE Leads Table` → `placeware_leads`) and adjust inserts.
- Adjust email subject/template branding in `db.py`.
- Update WP plugin slug, REST namespace, option keys, CSS variable prefix.

## Environment / Secrets (present)
`.env` in `backend/` expects: `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `SUPABASE_URL`, `SUPABASE_KEY`, `EMAIL_FROM`, `EMAIL_PASS`, `HF_TOKEN` (and future: `HF_API_URL`, `HF_API_KEY`, `SAGE_API_KEY`). Never commit real keys (current file contains live-looking values—sanitize before pushing!). Provide a `.env.example` during refactor.

## Retrieval & Embedding Contract
- Embedding length must be exactly 384; validation in `/chat` rejects otherwise.
- Supabase RPC `match_documents(query_embedding, match_threshold, match_count)` must return rows with `question`, `answer`.
- If retrieval yields no rows or DeepSeek returns empty string, fallback loads `config.yaml` → `company.services` to build a generic answer (`"PSE offers: ..."`) — this must be reworked to `Placeware offers:` or replaced by domain-specific fallback.

## Testing & Local Dev
- Ad-hoc test scripts only (`test_chat.py`, `test_deepseek.py`) — not pytest structured. They assume FastAPI on `localhost:8000`.
- To run backend locally (implicit): install `backend/requirements.txt`, then `uvicorn app:app --reload` inside `backend/` or run module section in `app.py`.
- Embedding proxy relies on external HF Space; for offline dev add a stub returning a zero or random 384-vector so tests don’t fail.

## Conventions & Patterns
- Minimal layering: FastAPI route → retrieval/LLM wrappers → fallback. No dependency injection—simple module singletons (`retriever`, `deepseek`). Keep changes consistent or introduce DI gradually.
- Error handling: Return JSON with `{"error": msg}` + proper status codes for validation/embedding failures. Keep this pattern for new endpoints.
- Logging: Uses `logging.info` / `logging.error` inline; expand consistently instead of prints.
- Email sending is synchronous in lead path—consider background task for scale but keep MVP simple.

## Safe Extension Guidelines
1. Centralize constants (bot name, disclaimer, embedding dim) in a new `src/constants.py`—update all references (avoid scattered strings).
2. Create migration script (SQL) for Supabase schema rename before code switches table names.
3. Add pytest harness (e.g., `tests/test_chat_basic.py`) mocking DeepSeek + Supabase RPC for deterministic CI.
4. Introduce `PLACEWARE_DISCLAIMER` appended in `deepseek.generate_response` wrapper layer rather than editing every call.
5. For new pharma stock/order features, keep them in a separate module namespace `src/domain/pharma/` to avoid tangling legacy Q&A code.

## Anti-Goals / Avoid
- Don’t hard-code secrets or embedding service URL in multiple files; reference a single env-driven constant.
- Don’t expand retrieval SQL in code—use Supabase RPC abstraction unless adding new RPC function.
- Don’t remove existing endpoints until replacement has parity (maintain `/chat` + `/submit_lead`).

## Quick Reference (Files)
- `backend/app.py` – FastAPI entry; modify here for new endpoints.
- `backend/src/retrieval.py` – Supabase vector similarity RPC.
- `backend/src/deepseek.py` – LLM wrapper (branding change required).
- `backend/src/db.py` – Lead persistence + email (table rename + subject update).
- `backend/src/embed_proxy.py` – External embedding call (swap to HF Inference later).
- `my-plugin(2)/` – WordPress integration (namespace rename).

## First Sprint Checklist (Suggested)
- Add `.env.example` (sanitized) + `src/constants.py`.
- Rename branding strings and table names (code + SQL migration doc).
- Implement disclaimer injection & update system prompt.
- Add minimal pytest suite mocking DeepSeek & Supabase.
- Produce WP plugin rename patch.

Provide diffs in small, isolated commits (branding, constants, tests, plugin rename) for easier review.
