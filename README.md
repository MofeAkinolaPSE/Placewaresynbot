Placeware / Synbot Platform

Current architecture target:
- Standalone SaaS app for admin UI + backend API.
- Backend is FastAPI in `backend/`.
- Frontend React app is in `SynbotUI/`.
- WordPress integration is a lightweight floating chat plugin in `placeware-chat-widget/`.

## Folders

- `backend/` — FastAPI API, auth, retrieval, analytics, migrations.
- `SynbotUI/` — standalone React admin frontend.
- `placeware-chat-widget/` — WordPress plugin for floating chat widget only.
- `plugin1/` — legacy plugin artifacts (no longer hosts admin React app).

## Local Development

Backend:
- `cd backend`
- `pip install -r requirements.txt`
- `python -m uvicorn app:app --reload`

Frontend:
- `cd SynbotUI`
- `pnpm install`
- `pnpm dev`

## Authentication

- OAuth2 password flow with custom JWT access tokens and refresh token rotation.
- Backend endpoints:
	- `POST /token`
	- `POST /refresh`
	- `POST /logout`
	- `GET /users` / `POST /users` / `PUT /users/{id}/password` / `PATCH /users/{id}/status` (admin only)

## WordPress Widget

- Install `placeware-chat-widget` plugin on client WP site.
- Configure API Base URL (your hosted backend) and optional site key.
- Widget sends chat prompts to backend `/chat`.

## Production Deployment (Swarm + Bridge)

This repo now supports a single VM entrypoint for first install and repeat-safe reruns.

1. Prepare secrets in both env files:
- VM app env: `backend/.env` (copy from `backend/.env.example`)
- Sage bridge env: `sage-bridge/.env` (copy from `sage-bridge/.env.example`)

2. On Sage Windows host:
- Start Sage desktop client.
- From `sage-bridge/`, run one helper command:
	- `powershell -ExecutionPolicy Bypass -File .\start_and_test.ps1 -SkipWrite`

This starts the bridge if needed and runs connectivity diagnostics in one step.

3. On Ubuntu VM host (after clone):
- First install:
	- `sudo bash deploy/start-stack.sh --first-run --install-deps`
- Repeat deploy:
	- `sudo bash deploy/start-stack.sh --redeploy`

4. Connectivity gate (phase 4):
- Connectivity checks are expected to run from `sage-bridge/` only.
- VM deploy remains lean and does not block by default.
- If you want strict enforcement on VM deploy, run:
	- `sudo bash deploy/start-stack.sh --first-run --install-deps --connectivity required`

Notes:
- `deploy/start-stack.sh` orchestrates `preflight-host.sh`, security hardening scripts, `init-swarm.sh`, and optional Let's Encrypt.
- Default TLS path is self-signed via `deploy/gen-tls-cert.sh` (already called by `init-swarm.sh`).