import pyodbc

# PLANIGLI is registered in dbnames.cfg - use the DB NAME not the path
tests = [
    "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=PLANIGLI;UID=Master;PWD=;",
    "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=planigli;UID=Master;PWD=;",
    "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=PLANIGLI;UID=PTBI_00000;PWD=;",
    "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=PLANIGLI;",
    "Driver={Pervasive ODBC Client Interface};ServerName=127.0.0.1;DBQ=PLANIGLI;UID=Master;PWD=;",
]

for cs in tests:
    label = cs[50:100]
    try:
        conn = pyodbc.connect(cs, timeout=10)
        print("OK  [%s]: CONNECTED!" % label)
        cursor = conn.cursor()
        tables = sorted([t.table_name for t in cursor.tables()])
        print("  Tables (%d): %s" % (len(tables), tables[:10]))
        conn.close()
        break
    except Exception as e:
        print("FAIL [%s]:" % label)
        print("  %s" % str(e)[:150])
