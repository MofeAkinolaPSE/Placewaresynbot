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