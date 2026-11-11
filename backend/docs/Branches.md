# Branches: Lagos and Abuja (7 Nov 2026)

One ACE runs both branches on one server and one app. Each branch has its own books, stock, customers, suppliers, Frontdesk, operations and quality records. HR, My Workspace, chat, tasks, notifications and the CRM pipeline are shared across the company.

## The model

- **A branch is an ACE Books legal entity.**
  - Lagos is the existing `PNL` entity (`is_primary`).
  - Abuja is `PNL-ABJ`, "Placeware Nigeria Limited - Abuja".
  - Branch names come from `fin_legal_entities.branch_name`.
- **Branch-owned tables carry `legal_entity_id`.** This covers:
  - all 52 ACE Books header tables (they already had it);
  - customers, suppliers, frontdesk_invoices and walk-ins, deliveries, riders and routes;
  - replenishment_requests, NAFDAC batches, recalls, deviations, equipment, maintenance, temperature and audits;
  - inventory events, AR alert rules and events, vendor payment requests, budget targets;
  - every `sage_*` snapshot.

  Existing rows were tagged Lagos. New rows take the request's branch through the column default `pw_entity_default()`.
- **Codes are unique per branch.** This applies to customer code, supplier vendor ID, recall and deviation IDs, NAFDAC batch, budget target and legacy invoice ID. Invoice numbering was already per entity, so Abuja continues its own Sage numbers once they are loaded.

## Who works where

- `placeware_users.home_entity_id` is the branch a login works in. `extra_entity_ids` lists other branches it may switch to.
- `admin` and `management` (CEO / CFO) may use every branch.
- These are set on User Access, in the Branch picker when creating a login or under Edit access. A reason is required and the change is audited.

## How a request gets its branch, and why it cannot leak

1. **The frontend sends the branch.** `client/lib/branch.ts` adds `X-Legal-Entity` to every signed-in fetch.
   - The branch is remembered per tab (sessionStorage); new tabs start from the last choice (localStorage).
   - Switching reloads the app.
   - The top bar shows `BranchSwitcher`: a badge, or a menu for people who can switch.
   - A link with `?branch=<code>` opens in that branch. Notifications use this, and their titles start "Abuja: ...".
2. **The middleware resolves it.** `src/branch.py` `BranchMiddleware` resolves the header against the login's access.
   - A branch the login may not use gets `403 BRANCH_NOT_ALLOWED`. It is never silently swapped. The app then forgets the choice and reloads in the home branch.
   - With no header, the request uses the home branch.
3. **The connection pool applies it.** `src/local_db.py` `WaitingConnectionPool.getconn` puts every connection into the branch: `SET ROLE ace_app` plus `app.entity_id`.
4. **Postgres enforces it.** Row-level security does the filtering:
   - Each branch table has a **RESTRICTIVE** policy `branch_isolation`. It must be restrictive, because old "allow all" policies from the Supabase days are OR-ed with any permissive one.
   - Every table with RLS enabled also has `ace_app_access`, so the web role sees exactly what the app always saw.
   - Views are `security_invoker`, so the filtering reaches through them.

   The result is that a query that forgets its branch filter returns nothing from the other branch. Writing a row into the other branch is refused.
5. **Caches are kept per branch.** These are keyed by branch through `branch.cache_key`:
   - `shared_response`
   - `src/cache.py`
   - `SimpleTTLCache` / `RedisTTLCache`
   - the staff workspace queue cache
6. **Thread pools carry the branch.** Work submitted to a thread pool uses `branch.carry(fn)`. This applies to Ask ACE's parallel tools, report sections and `batch_query`.

Outside a web request (start-up, background loops, scripts) there is no branch, and work runs as the owner, unfiltered. Use `with branch.scoped(entity_id):` to work in one branch, or `branch.unscoped()` for whole-database work such as backups (`routers/backup.py` `_whole_db_conn`).

Frontdesk postings always go into the invoice's own branch (`integrations.post_frontdesk_invoice`).

## Same features in every branch (9 Nov 2026)

Code is shared, so every Lagos fix applies to Abuja automatically. Branch parity can only break through **per-branch data**: anything a migration seeded for Lagos alone. These are now covered for every branch:

- **Invoice numbers.** All branches use Sage's plain running numbers. `numbering.next_number` continues from the branch's own Sage Sales Journal (`sage_invoice_floor`). A branch with no Sage history shows "Not set yet" on the Invoice register and refuses to invoice; it never invents "SI-000001". Finance can set the next number there with the Set button (`PUT /fin/settings/invoice-numbering`). That number can't be below one already used, and the Sage floor takes over once the branch's data is loaded.
- **Default customer.** "Sundry" is copied from Lagos (migration 150).
- **Goods received before the bill.** `GOODS_RECEIVED_ACCRUAL` → 23000 is now in `migration.DEFAULT_MAPPINGS`, so a branch's chart gets it on load, as Lagos got it from migration 131.
- **Other per-branch settings** (ageing buckets, credit-limit mode, ship methods, invoice layout) are copied from Lagos when the branch is created. The chart, posting rules, bank accounts, asset categories and periods come with the branch's Sage load (`bootstrap_defaults`).

When adding a migration that seeds per-entity data, seed it for **every** entity, not just `PNL`.

## Rules for new code

- **New branch-owned table:** add `legal_entity_id uuid NOT NULL DEFAULT pw_entity_default()`. `scripts/apply_migrations.py` runs `pw_apply_branch_security()` after every migration run. That adds grants, the policies and `security_invoker` on new views automatically.
- **New `ON CONFLICT` on a per-branch unique key:** include `legal_entity_id`.
- **Thread-pool work inside a request:** wrap the function in `branch.carry`.
- **A new query helper that bypasses `db.pool`** (a direct `psycopg2.connect`) runs unfiltered. Don't use one for branch data.

## Deploying

- `scripts/reload_database.sh` creates the `ace_app` role before loading a dump. Roles belong to the Postgres server, not to one database.
- The backend's start-up re-applies the grants. Always start the new backend image before or right after a reload. A restart re-runs `pw_apply_branch_security()`.

## Loading Abuja's data (next phase)

Abuja runs Sage 50 2016 or 2018; Lagos runs Sage 50 2013. These are the same Peachtree-line US edition, so the report exports have the same layouts and our existing loaders read them.

- **Preferred source:** the same export list used for Lagos (ACE-Books.md §11), exported from Abuja's Sage:
  - CoA, TB, GL
  - customer and vendor lists and ledgers
  - Sales, Purchase, Cash Receipts and Cash Disbursements Journals
  - Item list, Item Costing, Inventory Valuation
  - aged reports
- **A Sage backup** (`.ptb`, Actian/Pervasive data files) can only be opened by Sage 50 of the same or a newer version. Our 2013 install cannot restore it, so the reports would still need exporting from a 2016/2018 install.
- **Loading:** every loader works in the request's or context's branch. Run them with Abuja selected, or wrap a CLI run in `branch.scoped(<PNL-ABJ id>)`. Customers, suppliers, products, batches and the Sage history then land in Abuja only.

**Before Abuja goes live, set in Abuja's ACE Books › Setup:**
- invoice layout: Abuja's address, phones and bank (copied from Lagos at creation);
- cut-over date and auto-post.

Until Abuja's items exist, Frontdesk in Abuja refuses to invoice with a clear message.

## Tests

The scratchpad scripts below were run on dev on 7 Nov 2026:
- `branch_flow.py`: 31/31 (access, isolation, raw SQL under the web role, cross-branch writes refused, 285 GET routes × 2 branches with no 5xx).
- `fd_flow.py`: 17/17.
- `approve_post.py`: finance-only approval posts into Lagos, then voids.
- Playwright `branch_shots.js`: switching, `?branch=` links, User Access.

The dev backup taken before migration 150 is `backups/pre-branches-2026-11-07.dump`.
