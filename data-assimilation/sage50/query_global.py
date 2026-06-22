import pyodbc
cs = "Driver={Pervasive ODBC Client Interface};ServerName=localhost;DBQ=PEACHTREEGLOBAL;"
conn = pyodbc.connect(cs, timeout=5)
cur = conn.cursor()

for sql in [
    "SELECT * FROM [Licensed Users]",
    "SELECT TOP 3 * FROM [Serial Numbers]",
    "SELECT TOP 3 * FROM [Options]",
    "SELECT TOP 3 * FROM [EnvironmentSettings]",
    "SELECT TOP 5 * FROM [SmartPostingStatus]",
]:
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("=== %s ===" % sql)
        print("Cols: %s" % cols)
        for r in rows:
            print("  %s" % [str(x)[:60] if x else x for x in r])
    except Exception as e:
        print("FAIL [%s]: %s" % (sql[:40], str(e)[:100]))
conn.close()

# Also check Sage 50 config files for ODBC strings
import os
sage_paths = [
    r'C:\Sage\Peachtree\Company',
    r'C:\Sage\Peachtree',
    r'C:\Users\DELL\AppData\Roaming\Sage',
    r'C:\Users\DELL\AppData\Local\Sage',
]
print("\n=== Sage config files ===")
for path in sage_paths:
    if os.path.exists(path):
        for root, dirs, files in os.walk(path):
            for f in files:
                if f.lower().endswith(('.ini', '.cfg', '.xml', '.txt', '.ptb')):
                    print("  %s" % os.path.join(root, f))
            if root != path:
                break  # only one level
