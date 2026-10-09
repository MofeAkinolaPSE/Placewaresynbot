"""Simulate N laptops using ACE at once, through nginx, with the requests the real pages make.

usage:
    docker exec -w /backend chat-backend.v1 python tests/load/mint_tokens.py > tokens.json
    python backend/tests/load/loadtest.py tokens.json --users 50 --minutes 4

tokens.json: {"<role>": "<jwt>", ...}. Access tokens expire, so mint fresh ones before each run.
LT_BASE (default https://localhost) points at nginx; LT_STALE is how often (seconds) the
always-on requests (top bar, inbox, presence) repeat for one laptop.
"""
import argparse
import asyncio
import json
import os
import random
import statistics
import time
from collections import defaultdict

import httpx

BASE = os.getenv("LT_BASE", "https://localhost")
STALE = float(os.getenv("LT_STALE", "60"))
TODAY = time.strftime("%Y-%m-%d")
YEAR = time.strftime("%Y-01-01")
MONTH = time.strftime("%Y-%m-01")

# what every page shows: top bar, inbox badge, presence, licence banner, alerts bell
COMMON = ["/workspace/time", "/workspace/inbox?filter=all", "/presence/online", "/license/status",
          "/dashboard/alerts", ("POST", "/presence/heartbeat")]

PAGES = {
    "home": ["/workspace/day", "/workspace/prefs"],
    "executive": ["/dashboard/executive", "/dashboard/finance", "/dashboard/workforce"],
    "books_overview": ["/fin/context", f"/fin/dashboard?as_of={TODAY}", "/fin/data-exceptions?status=OPEN"],
    "books_sales": [f"/fin/sales/invoices?from={MONTH}&to={TODAY}&limit=300", f"/fin/reports/aged-receivables?as_of={TODAY}&basis=due"],
    "books_purchases": ["/fin/payables/bills", f"/fin/reports/aged-payables?as_of={TODAY}"],
    "books_ledger": [f"/fin/ledger/gl-summary?from={YEAR}&to={TODAY}"],
    "books_statements": [f"/fin/reports/income-statement?from={YEAR}&to={TODAY}", f"/fin/reports/balance-sheet?as_of={TODAY}"],
    "books_trial_balance": [f"/fin/ledger/trial-balance?as_of={TODAY}"],
    "books_stock": ["/fin/reports/stock-status", f"/fin/reports/inventory-valuation?as_of={TODAY}"],
    "books_banking": ["/fin/banking/accounts", "/fin/banking/vouchers"],
    "inventory": ["/inventory/items?limit=200", "/inventory/summary", "/dashboard/inventory"],
    "quality": ["/quality/overview", "/qc/dashboard", "/qc/expiry-alerts", "/quality/recalls", "/quality/batches"],
    "procurement": ["/procurement/stock-orders", "/procurement/stock-orders/summary", "/procurement/reorder-plan", "/procurement/suppliers"],
    "crm": ["/crm/customers?limit=300", "/dashboard/crm"],
    "frontdesk": ["/frontdesk/invoices", "/fin/products", "/crm/customers?limit=300"],
    "hr": ["/hr/overview", "/hr/people", "/workspace/team"],
    "logistics": ["/logistics/deliveries"],
}
ROLE_PAGES = {
    "sales": ["home", "crm", "frontdesk", "inventory"],
    "frontdesk": ["home", "frontdesk", "crm", "inventory"],
    "finance": ["books_overview", "books_sales", "books_purchases", "books_ledger", "books_statements",
                "books_trial_balance", "books_stock", "books_banking", "executive"],
    "ops": ["home", "inventory", "procurement", "logistics", "quality"],
    "quality_assurance": ["home", "quality", "inventory"],
    "procurement": ["home", "procurement", "inventory"],
    "hr": ["home", "hr"],
    "management": ["executive", "books_overview", "books_statements", "hr", "crm"],
    "admin": ["executive", "home", "books_overview", "hr", "inventory"],
}
MIX = {"sales": 10, "frontdesk": 6, "finance": 6, "ops": 6, "quality_assurance": 5, "procurement": 4,
       "hr": 2, "management": 3, "admin": 2}

stats = defaultdict(list)                          # path -> [latency_ms]
errors = defaultdict(lambda: defaultdict(int))     # path -> status -> n


def key(path: str) -> str:
    return path.split("?")[0]


async def call(client, token, item):
    method, path = item if isinstance(item, tuple) else ("GET", item)
    t0 = time.perf_counter()
    try:
        r = await client.request(method, BASE + path, headers={"Authorization": f"Bearer {token}"}, timeout=90)
        status = r.status_code
    except Exception as exc:
        status = type(exc).__name__
    stats[key(path)].append((time.perf_counter() - t0) * 1000)
    if status != 200:
        errors[key(path)][status] += 1


async def user(role, token, deadline):
    limits = httpx.Limits(max_connections=6)       # a browser opens about six connections per site
    async with httpx.AsyncClient(verify=False, limits=limits) as client:
        await asyncio.sleep(random.uniform(0, 10))  # people don't all arrive in the same second
        fetched = -1e9
        while time.monotonic() < deadline:
            page = random.choice(ROLE_PAGES[role])
            common = COMMON if time.monotonic() - fetched >= STALE else []
            if common:
                fetched = time.monotonic()
            await asyncio.gather(*(call(client, token, x) for x in common + PAGES[page]))
            await asyncio.sleep(random.uniform(5, 15))  # reading the page before the next click


def p95(v):
    return statistics.quantiles(v, n=20)[18] if len(v) > 1 else v[0]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tokens")
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--minutes", type=float, default=4)
    a = ap.parse_args()
    tokens = json.load(open(a.tokens))
    scale = a.users / sum(MIX.values())
    people = [(r, tokens[r]) for r, n in MIX.items() for _ in range(max(1, round(n * scale)))]
    deadline = time.monotonic() + a.minutes * 60
    t0 = time.monotonic()
    await asyncio.gather(*(user(r, t, deadline) for r, t in people))
    took = time.monotonic() - t0
    total = sum(len(v) for v in stats.values())
    bad = sum(n for e in errors.values() for n in e.values())
    allms = [m for v in stats.values() for m in v]
    print(f"{len(people)} laptops, {took:.0f}s, {total} requests ({total / took:.1f}/s), errors {bad} ({100 * bad / max(total, 1):.2f}%)")
    print(f"all requests: p50 {statistics.median(allms):.0f} ms, p95 {p95(allms):.0f} ms, max {max(allms):.0f} ms\n")
    print(f"{'endpoint':45} {'n':>5} {'p50':>6} {'p95':>6} {'max':>7}  errors")
    for path, v in sorted(stats.items(), key=lambda kv: -p95(kv[1])):
        print(f"{path[:45]:45} {len(v):>5} {statistics.median(v):>6.0f} {p95(v):>6.0f} {max(v):>7.0f}  {dict(errors.get(path, {})) or ''}")


if __name__ == "__main__":
    asyncio.run(main())
