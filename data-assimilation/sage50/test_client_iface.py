import pyodbc

tests = [
    ("Client+localhost+path", "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=C:\\SageData\\planigli;"),
    ("Client+127.0.0.1+path", "Driver={Pervasive ODBC Client Interface};ServerName=127.0.0.1;DBQ=C:\\SageData\\planigli;"),
    ("Client+named-db", "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=planigli;"),
    ("Client+no-server", "Driver={Pervasive ODBC Client Interface};DBQ=C:\\SageData\\planigli;"),
    ("DSN=PLANIGLI", "DSN=PLANIGLI;"),
]

for name, cs in tests:
    try:
        conn = pyodbc.connect(cs, timeout=8)
        print("OK [%s]: CONNECTED!" % name)
        cursor = conn.cursor()
        tables = [t.table_name for t in cursor.tables()]
        print("  Tables: %s" % tables[:5])
        conn.close()
        break
    except Exception as e:
        print("FAIL [%s]: %s" % (name, str(e)[:120]))
