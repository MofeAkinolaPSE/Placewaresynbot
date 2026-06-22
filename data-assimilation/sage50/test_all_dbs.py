"""Test all registered named databases and compare which ones work."""
import pyodbc

# All registered databases found in dbnames.cfg
db_names = [
    "defaultdb", "demodata", "pervasivesysdb", "tempdb",
    "PEACHTREEGLOBAL", "PLACEWARELIMTEDDEMO", "PLANIGLI",
]

for db in db_names:
    cs = "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=%s;" % db
    try:
        conn = pyodbc.connect(cs, timeout=5)
        tables = [t.table_name for t in conn.cursor().tables()]
        print("OK  %-25s  tables=%d" % (db, len(tables)))
        conn.close()
    except Exception as e:
        err = str(e)[:80]
        print("FAIL %-25s  %s" % (db, err))
