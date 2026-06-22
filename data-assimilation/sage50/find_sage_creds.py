"""
Try Windows integrated auth and inspect PEACHTREEGLOBAL for Sage security config.
"""
import pyodbc

base = "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=%s;"

# Windows integrated / Trusted Connection attempts
print("=== Windows auth attempts on PLACEWARELIMTEDDEMO ===")
win_tests = [
    "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=PLACEWARELIMTEDDEMO;Trusted_Connection=Yes;",
    "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=PLACEWARELIMTEDDEMO;IntegratedSecurity=SSPI;",
    "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=PLACEWARELIMTEDDEMO;UID=DELL;PWD=;",
    "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=PLACEWARELIMTEDDEMO;UID=DESKTOP-1RC23AJ\\DELL;PWD=;",
]
for cs in win_tests:
    try:
        conn = pyodbc.connect(cs, timeout=5)
        tbls = [t.table_name for t in conn.cursor().tables()]
        print("  CONNECTED: %s" % cs[50:80])
        print("  Tables: %s" % tbls[:5])
        conn.close()
    except Exception as e:
        code = str(e)[:20]
        print("  FAIL [%s]: %s" % (cs[50:70], code))

# Now query PEACHTREEGLOBAL for security/user configuration
print("\n=== PEACHTREEGLOBAL tables and security config ===")
cs_global = base % "PEACHTREEGLOBAL"
try:
    conn = pyodbc.connect(cs_global, timeout=5)
    cursor = conn.cursor()
    tbls = sorted([t.table_name for t in cursor.tables()])
    print("Tables (%d): %s" % (len(tbls), tbls))

    # Look for user/security/permission tables
    sec_tables = [t for t in tbls if any(k in t.lower() for k in ['user', 'secur', 'perm', 'auth', 'pass', 'role'])]
    print("Security-related tables: %s" % sec_tables)

    for t in sec_tables[:3]:
        try:
            cursor.execute("SELECT TOP 5 * FROM [%s]" % t)
            rows = cursor.fetchall()
            cols = [d[0] for d in cursor.description]
            print("\n%s: cols=%s" % (t, cols))
            for r in rows:
                print("  %s" % list(r))
        except Exception as e:
            print("  %s: %s" % (t, str(e)[:80]))

    # Check X$User in PEACHTREEGLOBAL
    try:
        cursor.execute("SELECT * FROM X$User")
        users = cursor.fetchall()
        ucols = [d[0] for d in cursor.description]
        print("\nX$User: %s" % ucols)
        for u in users:
            print("  %s" % list(u))
    except Exception as e:
        print("X$User: %s" % str(e)[:80])

    conn.close()
except Exception as e:
    print("PEACHTREEGLOBAL failed: %s" % str(e)[:100])
