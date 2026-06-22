import pyodbc

# demodata is a registered named database - test if we can connect
cs = "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=demodata;"
print("Trying demodata connection...")
try:
    conn = pyodbc.connect(cs, timeout=8)
    print("CONNECTED to demodata!")
    cursor = conn.cursor()
    tables = sorted([t.table_name for t in cursor.tables()])
    print("Tables: %s" % tables)

    # Try CREATE DATABASE planigli
    print("\nTrying CREATE DATABASE planigli...")
    try:
        cursor.execute("CREATE DATABASE planigli")
        conn.commit()
        print("CREATE DATABASE: SUCCESS!")
    except Exception as e:
        print("CREATE DATABASE failed: %s" % str(e)[:200])

    # Try with path variations
    for sql in [
        "CREATE DATABASE planigli PATH 'C:\\SageData\\planigli'",
        "CREATE DATABASE planigli DBPATH='C:\\SageData\\planigli'",
        "CREATE DATABASE 'C:\\SageData\\planigli' DBNAME=planigli",
    ]:
        try:
            cursor.execute(sql)
            conn.commit()
            print("SUCCESS with: %s" % sql[:60])
        except Exception as e:
            print("FAIL: %s\n  -> %s" % (sql[:60], str(e)[:120]))

    conn.close()
except Exception as e:
    print("FAILED to connect: %s" % str(e)[:200])
