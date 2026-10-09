# ZAP scan of 8 Oct 2026: remediation

Scan: `2026-10-08-ZAP-Report-placewareaiapp.online.md`. It found 0 High, 1 Medium, 2 Low and 1 Informational alert.

## Findings and fixes

| Alert | Risk | Cause | Fix |
| --- | --- | --- | --- |
| Content Security Policy (CSP) Header Not Set | Medium | No CSP was configured anywhere. | A CSP is now sent on every HTTPS response (`SynbotUI/security-headers.conf` and the `map $uri $csp` in `SynbotUI/nginx.conf`). |
| Strict-Transport-Security Header Not Set (on `/assets/*.js`, `*.css`) | Low | The static-assets location sets its own `Cache-Control` with `add_header`. In nginx, that discards every server-level `add_header`, so assets went out with no security headers at all. | Every location that uses `add_header` now includes the shared header snippet as well. |
| X-Content-Type-Options Header Missing (same assets) | Low | Same cause. | Same fix. |
| Modern Web Application | Info | Not a vulnerability: it reports that the site is a single-page app. | No change. |

## Headers now sent

On every HTTPS response: the page, the assets, API responses and error pages.

- **`Content-Security-Policy`**
  - The app allows `script-src 'self'` only: no inline script and no `eval`.
  - Styles may come from the app (inline included), Google Fonts and unpkg (Leaflet CSS).
  - Fonts may come from fonts.gstatic.
  - Images may come from any https origin (map tiles, marker icons).
  - `connect-src` is the same host only, including `wss://` for the realtime channels.
  - `object-src 'none'`, `frame-ancestors 'self'`, `base-uri 'self'`, `form-action 'self'`, `upgrade-insecure-requests`.
  - Only `/docs` and `/redoc` (FastAPI's API explorer) also allow jsDelivr and an inline bootstrap script.
- **`Strict-Transport-Security: max-age=31536000; includeSubDomains`**
- **`X-Content-Type-Options: nosniff`**
- **`X-Frame-Options: SAMEORIGIN`**
- **`Referrer-Policy: strict-origin`**
- **`Permissions-Policy: camera=(), microphone=(), geolocation=(self), payment=(), usb=()`**
  - It previously set `geolocation=()`, which blocked the CRM Lead Finder's "use my location" and rider GPS tracking.
- **`X-Permitted-Cross-Domain-Policies: none`**
- **`X-XSS-Protection: 0`**: the legacy XSS auditor is switched off, as OWASP advises, now that CSP is in place.

## Code changes needed for the CSP

The Frontdesk "Print / Save as PDF" popup (`client/components/frontdesk/InvoicesTab.tsx`, `printInvoice`) had two problems:

1. **It relied on inline JavaScript**: an `onclick` attribute and a `<script>` tag. The CSP blocks both, so the print button and the auto-print are now attached from the app's own code.
2. **It was an XSS hole.** It wrote customer names, addresses, PO numbers, product names and batch numbers into HTML without escaping. The popup runs in the app's origin, so a crafted customer name could run script and read the session. Every value is now HTML-escaped.

## Verified on dev (8 Oct 2026)

- `nginx -t` passes.
- **Headers:** present on `/`, `/sitemap.xml`, `/assets/*.js`, `/assets/*.css`, an API 401 response, `/docs` and `/health`.
- **Pages:** 22 pages loaded in Chromium with a CSP-violation listener, with zero violations. The pages covered:
  - Dashboard, Executive Overview
  - ACE Books: home, sales, register, ledger, statements, Report Center, assets, invoice print
  - Credit Control, Frontdesk
  - CRM: overview, Lead Finder, customers
  - Logistics, Workspace, HR, Inventory, Quality, Ask ACE, Admin
- **The CSP is enforcing:** an injected inline script was blocked and reported.
- **The Logistics Live Map** loads OpenStreetMap tiles and the Leaflet CSS with no violations.
- **The Frontdesk print popup** opens with the invoice, its print button is wired, it contains no `<script>`, and there are no violations.

## To deploy on the client server

The headers ship inside the frontend image, so rebuild the frontend there:

```
cd backend
docker compose build frontend
docker compose up -d frontend
docker exec placeware-frontend.v1 nginx -t
curl -skI https://placewareaiapp.online/ | grep -iE "content-security|strict-transport|x-content-type"
```

Then rerun the ZAP baseline scan against https://placewareaiapp.online. All three alerts should be gone.

## Also locked down (found during this work)

**API explorer closed to the public.** `/docs`, `/redoc` and `/openapi.json` listed every API route without login. nginx now returns 404 for them. They were not made "admin-only" because a browser opening `/docs` directly sends no login token, so the backend cannot tell who is asking. Developers on the server still have them at `http://localhost:8000/docs`.

**Backend port bound to loopback.** `docker-compose.yml` published the backend as `8000:8000` on every network interface. Anyone who could reach the server on port 8000 talked to the API directly, bypassing nginx: no HTTPS, no security headers, no rate limits. It is now `127.0.0.1:8000:8000`, so only the server itself can use it. All outside traffic goes through nginx on 443.

Both are verified on dev:

- The docs paths return 404 through nginx, and `/documents` still reaches the API.
- `localhost:8000/docs` still answers on the server.
- `docker port` shows `127.0.0.1:8000`.
- All 22 pages still load with no CSP violations.

On the client server, `docker compose up -d backend frontend` applies both, after the frontend rebuild above.

## Recommended next

**Run a ZAP authenticated and active scan, not only the baseline.** The baseline scan only sees the public pages and passively checks headers. An authenticated active scan exercises the API itself.
