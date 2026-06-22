import pyodbc

base = "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=C:\\SageData\\planigli;"

creds = [
    ("Master", ""),
    ("PTBI_00000", ""),
    ("", ""),
]

for uid, pwd in creds:
    cs = base + ("UID=%s;PWD=%s;" % (uid, pwd))
    try:
        conn = pyodbc.connect(cs, timeout=8)
        print("OK  uid='%s' pwd='%s': CONNECTED!" % (uid, pwd))
        cursor = conn.cursor()
        tables = sorted([t.table_name for t in cursor.tables()])
        print("  Tables (%d): %s" % (len(tables), tables[:8]))
        conn.close()
    except Exception as e:
        print("FAIL uid='%s' pwd='%s':" % (uid, pwd))
        print("  Full error: %s" % str(e))
        print()
