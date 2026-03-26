"""
diag_inventory.py — one-shot diagnostic for sage_inventory_snapshot
Run: python diag_inventory.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from src.db import db

print("=" * 60)
print("DIAGNOSTIC: sage_inventory_snapshot")
print("=" * 60)

# 1. Total row count
try:
    r = db.table("sage_inventory_snapshot").select("id", count="exact").execute()
    total = r.count if r.count is not None else len(r.data or [])
    print(f"\n[1] Total rows in table: {total}")
except Exception as e:
    print(f"[1] ERROR counting rows: {e}")

# 2. Distinct batch_ids present
try:
    r = db.table("sage_inventory_snapshot").select("batch_id").execute()
    batch_ids = set(row.get("batch_id") for row in (r.data or []))
    print(f"\n[2] Distinct batch_ids: {batch_ids}")
except Exception as e:
    print(f"[2] ERROR fetching batch_ids: {e}")

# 3. Latest 5 rows (no filter)
try:
    r = db.table("sage_inventory_snapshot") \
        .select("id,sku,name,quantity,batch_id,imported_at") \
        .order("imported_at", desc=True) \
        .limit(5) \
        .execute()
    print(f"\n[3] Latest 5 rows (no filter):")
    for row in (r.data or []):
        print(f"    {row}")
except Exception as e:
    print(f"[3] ERROR fetching rows: {e}")

# 4. What _latest_batch_for_table returns
try:
    r = db.table("sage_inventory_snapshot").select("batch_id").order("imported_at", desc=True).limit(1).execute()
    latest_batch = (r.data or [{}])[0].get("batch_id")
    print(f"\n[4] _latest_batch_for_table returns: {repr(latest_batch)}")
except Exception as e:
    print(f"[4] ERROR: {e}")

# 5. Row count WITH that batch_id filter
try:
    r2 = db.table("sage_inventory_snapshot").select("batch_id").order("imported_at", desc=True).limit(1).execute()
    bid = (r2.data or [{}])[0].get("batch_id")
    if bid:
        r3 = db.table("sage_inventory_snapshot").select("id", count="exact").eq("batch_id", bid).execute()
        cnt = r3.count if r3.count is not None else len(r3.data or [])
        print(f"\n[5] Rows matching batch_id={repr(bid)}: {cnt}")
    else:
        print("\n[5] batch_id is NULL — filter would return 0 rows")
except Exception as e:
    print(f"[5] ERROR: {e}")

# 6. Check kpi_promotions table
try:
    r = db.table("sage_kpi_promotions").select("domain,batch_id,promoted_at").limit(5).execute()
    print(f"\n[6] sage_kpi_promotions rows: {r.data}")
except Exception as e:
    print(f"[6] kpi_promotions check: {e}")

print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
