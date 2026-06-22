"""
Extract Sage 50 financial data by temporarily redirecting the 'demodata'
registered database to the planigli directory.

Strategy:
1. Backup demodata directory
2. Create junction: demodata dir → C:\SageData\planigli
3. Connect to 'demodata' ODBC (now reads planigli schema + data)
4. Extract all target tables
5. Restore original demodata directory

Run as ADMINISTRATOR (needs junction creation).
"""
import pyodbc
import csv
import os
import shutil
import subprocess
import time

PLANIGLI_DIR  = r'C:\SageData\planigli'
DEMODATA_DIR  = r'C:\ProgramData\Pervasive Software\PSQL\Demodata'
DEMODATA_BACK = r'C:\ProgramData\Pervasive Software\PSQL\Demodata_sage_backup'
OUT_DIR       = r'C:\Users\DELL\Desktop\Moe\Chat Assisant  placeware x1\data-assimilation\sage50\extracted'

os.makedirs(OUT_DIR, exist_ok=True)

TABLES = [
    'JrnlHdr', 'JrnlRow', 'InventoryCosts', 'Chart',
    'BankRecords', 'Budgets', 'Tax_Code', 'Vendors',
    'Customers', 'LineItem',
]

def connect():
    cs = "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=demodata;"
    return pyodbc.connect(cs, timeout=15)

def export_table(conn, table, outfile):
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM [%s]" % table)
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        with open(outfile, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        print("  %-25s %5d rows → %s" % (table, len(rows), os.path.basename(outfile)))
        return len(rows)
    except Exception as e:
        print("  %-25s FAILED: %s" % (table, str(e)[:100]))
        return 0

print("=== Sage 50 Extraction via Demodata Junction ===\n")

# Step 1: Verify current demodata connection works
print("Verifying demodata connection before swap...")
try:
    conn = connect()
    tbls = [t.table_name for t in conn.cursor().tables()]
    print("  Connected. Tables: %s" % tbls[:5])
    conn.close()
except Exception as e:
    print("  FAIL: %s" % e)
    exit(1)

# Step 2: Backup demodata directory
if os.path.isdir(DEMODATA_BACK):
    print("Backup already exists at %s" % DEMODATA_BACK)
elif os.path.isdir(DEMODATA_DIR):
    print("Backing up demodata to %s" % DEMODATA_BACK)
    shutil.copytree(DEMODATA_DIR, DEMODATA_BACK)
    shutil.rmtree(DEMODATA_DIR)
    print("  Backup done, original removed")
else:
    print("ERROR: demodata dir not found: %s" % DEMODATA_DIR)
    exit(1)

# Step 3: Create junction
print("Creating junction: %s -> %s" % (DEMODATA_DIR, PLANIGLI_DIR))
result = subprocess.run(['cmd', '/c', 'mklink', '/J', DEMODATA_DIR, PLANIGLI_DIR],
                        capture_output=True, text=True)
if result.returncode != 0:
    print("  Junction creation FAILED: %s" % result.stderr)
    # Restore backup
    os.rename(DEMODATA_BACK, DEMODATA_DIR)
    exit(1)
print("  Junction created")
time.sleep(2)

# Step 4: Connect and extract
print("\nConnecting to 'demodata' (now pointing to planigli)...")
try:
    conn = connect()
    tbls = sorted([t.table_name for t in conn.cursor().tables()])
    print("  Tables (%d): %s" % (len(tbls), tbls[:8]))

    if 'JrnlRow' in tbls or 'JRNLROW' in tbls:
        print("\n  Sage 50 tables detected! Extracting...")
        total = 0
        for t in TABLES:
            # Try exact name and variants
            actual = next((x for x in tbls if x.upper() == t.upper()), None)
            if actual:
                outfile = os.path.join(OUT_DIR, '%s.csv' % t.lower().replace(' ', '_'))
                total += export_table(conn, actual, outfile)
            else:
                print("  %-25s NOT FOUND in table list" % t)
        print("\nTotal rows extracted: %d" % total)
    else:
        print("  Still seeing demodata tables — junction may not have taken effect")
        print("  Tables: %s" % tbls[:10])
    conn.close()
except Exception as e:
    print("  Connection failed: %s" % str(e)[:150])

# Step 5: Restore
print("\nRestoring original demodata directory...")
if os.path.islink(DEMODATA_DIR) or (os.path.isdir(DEMODATA_DIR) and os.stat(DEMODATA_DIR).st_file_attributes & 0x400):
    subprocess.run(['cmd', '/c', 'rmdir', DEMODATA_DIR], capture_output=True)
if os.path.isdir(DEMODATA_BACK):
    os.rename(DEMODATA_BACK, DEMODATA_DIR)
    print("  Original demodata restored")
print("\nDone.")
