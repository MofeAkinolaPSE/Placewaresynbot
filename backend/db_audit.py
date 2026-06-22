"""
DB Audit Script — Placeware / Synbot Demo
Run with: docker exec chat-backend.v1 python /backend/db_audit.py
"""
import os
import psycopg2
from datetime import date

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:admin1234@db:5432/synbot_demo",
)

G = "\033[92m"
Y = "\033[93m"
R = "\033[91m"
B = "\033[94m"
W = "\033[97m"
RESET = "\033[0m"


def short(val, n=36):
    s = str(val) if val is not None else "NULL"
    return (s[:n] + "…") if len(s) > n else s


def section(title):
    print(f"\n{B}{'─' * 64}{RESET}")
    print(f"{W}  {title}{RESET}")
    print(f"{B}{'─' * 64}{RESET}")


def audit(conn, table, cols, expected=1, sample=3):
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]

        if count == 0:
            flag = f"{R}✗  EMPTY{RESET}"
        elif count >= expected:
            flag = f"{G}✓  {count:,} rows{RESET}"
        else:
            flag = f"{Y}⚠  {count:,} rows  (expected ≥{expected}){RESET}"

        print(f"\n  {W}{table}{RESET}")
        print(f"  Count : {flag}")

        if count > 0 and sample > 0:
            col_str = ", ".join(cols)
            cur.execute(f"SELECT {col_str} FROM {table} LIMIT {sample}")
            rows = cur.fetchall()
            names = [d[0] for d in cur.description]
            header = " | ".join(f"{n[:20]:<20}" for n in names)
            print(f"  {Y}{header}{RESET}")
            for row in rows:
                line = " | ".join(f"{short(v):<20}" for v in row)
                print(f"  {line}")
        elif count == 0:
            print(f"  {R}  (no rows){RESET}")

    except Exception as e:
        conn.rollback()   # clear aborted transaction so next query works
        print(f"\n  {R}{table}  —  QUERY ERROR: {e}{RESET}")
    finally:
        cur.close()


def count_only(conn, table, expected=1):
    """Return (count, flag_str) without fetching rows — used in summary."""
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        cur.close()
        return count
    except Exception as e:
        conn.rollback()
        cur.close()
        raise e


def main():
    print(f"\n{W}{'=' * 64}")
    print("  PLACEWARE DATABASE AUDIT")
    print(f"  Date : {date.today()}")
    print(f"  DB   : {DB_URL.split('@')[-1]}")
    print(f"{'=' * 64}{RESET}")

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False

    # ── 1. SAGE 50 IMPORT — CORE TABLES ─────────────────────────────────────
    section("1. SAGE 50 IMPORT — LIVE MASTER TABLES")

    audit(conn, "customers",
          ["id", "name", "customer_code", "client_type", "created_at"],
          expected=100)

    audit(conn, "sage_customers_snapshot",
          ["id", "customer_id", "name", "email", "imported_at"],
          expected=100)

    audit(conn, "sage_items_snapshot",
          ["id", "item_id", "item_name", "sell_price", "expiry_date", "batch_number"],
          expected=50)

    audit(conn, "sage_vendors_snapshot",
          ["id", "vendor_id", "vendor_name", "contact_name", "imported_at"],
          expected=5)

    audit(conn, "sage_coa_snapshot",
          ["id", "account_code", "account_name", "account_type"],
          expected=30)

    # ── 2. GL & FINANCIAL ────────────────────────────────────────────────────
    section("2. GL & FINANCIAL DATA")

    audit(conn, "sage_gl_transactions",
          ["id", "post_date", "gl_account", "description"],
          expected=1000)

    audit(conn, "sage_gl_snapshot",
          ["id", "account_code", "description", "imported_at"],
          expected=0)

    audit(conn, "sage_ar_snapshot",
          ["id", "customer_id", "invoice_number", "balance"],
          expected=0)

    audit(conn, "sage_ap_snapshot",
          ["id", "vendor_id", "invoice_number", "balance"],
          expected=0)

    audit(conn, "sage_inventory_snapshot",
          ["id", "sku", "name", "quantity", "expiry_date"],
          expected=1)

    # ── 3. CRM & LEADS ───────────────────────────────────────────────────────
    section("3. CRM & LEADS")

    audit(conn, "crm_prospects",
          ["id", "company_name", "contact_name", "source", "created_at"],
          expected=500)

    audit(conn, "leads",
          ["id", "company_name", "stage", "source", "created_at"],
          expected=100)

    audit(conn, "crm_pipeline_snapshot",
          ["id", "customer_id", "amount", "status"],
          expected=0)

    # ── 4. INVENTORY OPERATIONAL ─────────────────────────────────────────────
    section("4. INVENTORY — OPERATIONAL TABLES")

    audit(conn, "inventory_items",
          ["id", "sku", "name", "quantity", "created_at"],
          expected=0)

    audit(conn, "placeware_inventory_snapshot",
          ["id", "sku", "product_name", "current_qty", "imported_at"],
          expected=0)

    # ── 5. USERS ─────────────────────────────────────────────────────────────
    section("5. USERS & AUTHENTICATION")

    audit(conn, "placeware_users",
          ["id", "email", "roles", "is_active", "created_at"],
          expected=1)

    # ── 6. KNOWLEDGE BASE ────────────────────────────────────────────────────
    section("6. KNOWLEDGE BASE  (empty until docs uploaded via UI)")

    audit(conn, "qna",
          ["id", "question", "source"],
          expected=0)

    audit(conn, "knowledge_chunks",
          ["id", "title", "content"],
          expected=0)

    audit(conn, "ingested_documents",
          ["id", "filename", "status", "created_at"],
          expected=0)

    # ── 7. SUPPLIERS ─────────────────────────────────────────────────────────
    section("7. SUPPLIERS")

    audit(conn, "suppliers",
          ["id", "name", "contact_name", "contact_email", "created_at"],
          expected=0)

    # ── 8. SYSTEM ────────────────────────────────────────────────────────────
    section("8. SYSTEM / ACTIVITY")

    audit(conn, "placeware_chat_history",
          ["id", "user_id", "question", "created_at"],
          expected=0)

    audit(conn, "placeware_audit_logs",
          ["id", "event_type", "actor_id", "outcome", "created_at"],
          expected=0)

    audit(conn, "placeware_users",
          ["email", "roles", "is_active"],
          expected=1)

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    print(f"\n{B}{'=' * 64}{RESET}")
    print(f"{W}  SUMMARY — CRITICAL TABLES{RESET}")
    print(f"{B}{'=' * 64}{RESET}\n")

    critical = [
        ("customers",                "Live customer master",          100),
        ("sage_customers_snapshot",  "Sage customers (raw snapshot)", 100),
        ("sage_items_snapshot",      "Sage inventory SKUs",            50),
        ("sage_gl_transactions",     "GL journal entries",           1000),
        ("sage_vendors_snapshot",    "Sage vendors",                    5),
        ("sage_coa_snapshot",        "Chart of accounts",              30),
        ("crm_prospects",            "Lead finder prospects",         500),
        ("leads",                    "Sales CRM leads",               100),
        ("placeware_users",          "Auth users",                      1),
    ]

    all_ok = True
    for table, label, expected in critical:
        try:
            count = count_only(conn, table, expected)
            if count >= expected:
                flag = f"{G}✓  {count:>7,}{RESET}"
                note = ""
            elif count > 0:
                flag = f"{Y}⚠  {count:>7,}{RESET}"
                note = f"  ← low (expected ≥{expected})"
                all_ok = False
            else:
                flag = f"{R}✗   EMPTY{RESET}"
                note = f"  {R}← PROBLEM: no data{RESET}"
                all_ok = False
            print(f"  {flag}  {W}{table:<35}{RESET}  {label}{note}")
        except Exception as e:
            print(f"  {R}ERROR  {table:<35}{RESET}  {e}")
            all_ok = False

    print()
    if all_ok:
        print(f"{G}  ✓  All critical tables populated — database is deployment-ready.{RESET}\n")
    else:
        print(f"{R}  ✗  One or more critical tables are empty — see details above.{RESET}\n")

    conn.close()


if __name__ == "__main__":
    main()
