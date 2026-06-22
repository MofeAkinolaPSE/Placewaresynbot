import pyodbc

# Connect to pervasivesysdb - it has stored procedures for system operations
for dbname in ["pervasivesysdb", "defaultdb", "demodata"]:
    cs = "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=%s;" % dbname
    try:
        conn = pyodbc.connect(cs, timeout=8)
        print("CONNECTED to %s" % dbname)
        cursor = conn.cursor()

        # List stored procedures
        procs = [p.procedure_name for p in cursor.procedures()]
        print("  Procedures (%d): %s" % (len(procs), procs[:15]))

        # Try to list registered databases via system tables
        for tbl in ["X$File", "X$Field"]:
            try:
                cursor.execute("SELECT TOP 3 * FROM %s" % tbl)
                rows = cursor.fetchall()
                cols = [d[0] for d in cursor.description]
                print("  %s cols: %s" % (tbl, cols[:8]))
            except Exception:
                pass

        # Check if there's a system catalog with database entries
        try:
            cursor.execute("SELECT * FROM X$User")
            users = cursor.fetchall()
            ucols = [d[0] for d in cursor.description]
            print("  Users: cols=%s, rows=%d" % (ucols, len(users)))
            for u in users[:5]:
                print("    %s" % list(u))
        except Exception as e:
            print("  X$User: %s" % str(e)[:80])

        conn.close()
        break
    except Exception as e:
        print("FAIL %s: %s" % (dbname, str(e)[:80]))
