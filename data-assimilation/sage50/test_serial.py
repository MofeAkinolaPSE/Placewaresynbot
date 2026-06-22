import pyodbc
serial  = "30EA4-83B9-19E2-79AC"
serial2 = "30EA483B919E279AC"

for db in ["PLACEWARELIMTEDDEMO"]:
    for uid, pwd in [
        ("PTBI_00000", serial),
        ("PTBI_00000", serial2),
        ("PTBI_00000", serial.replace("-","")),
        ("Master", serial),
        ("Administrator", serial),
        ("Administrator", ""),
        ("PTBI_00000", "30EA4"),
    ]:
        cs = "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=%s;UID=%s;PWD=%s;" % (db, uid, pwd)
        try:
            conn = pyodbc.connect(cs, timeout=5)
            tbls = [t.table_name for t in conn.cursor().tables()]
            print("CONNECTED! uid=%s pwd=%s  tables=%d: %s" % (uid, pwd, len(tbls), tbls[:5]))
            conn.close()
        except Exception as e:
            err = str(e)[:80]
            if "28000" in str(e):
                print("auth-fail  uid=%-15s pwd=%s" % (uid, pwd[:20]))
            else:
                print("other-fail: %s" % err[:60])
