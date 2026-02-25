# WordPress Chat Widget Spec (MVP)

Goal: WordPress hosts only the floating chat widget. Admin UI is moved to standalone SaaS frontend (`SynbotUI`).

## Scope
- Include chat launcher and chat window on public/client site pages.
- Send prompts to backend `POST /chat`.
- Keep plugin small and dependency-free (vanilla JS/CSS).

## Settings (WP Admin)
- Backend API Base URL
- Optional site key (for per-site identification)

## Plugin Behavior
- Enqueue widget JS and CSS on frontend pages.
- Render floating launcher in footer.
- On submit, call `<API_BASE>/chat` with JSON payload `{ "question": "..." }`.

## Auth & Security
- No admin JWT in WordPress plugin.
- Use site key or signed widget token in headers when backend-side site validation is enabled.
- Restrict CORS to approved client domains.

## Out of Scope
- No analytics/reporting/admin panels in WordPress.
- No Sage import/admin workflows inside WP.

## Future
- Signed widget tokens with expiry.
- Per-site branding controls (logo/colors).
- Lightweight chat telemetry (latency/error tracking).
