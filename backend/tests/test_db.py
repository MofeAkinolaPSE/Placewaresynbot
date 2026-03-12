# test_db.py
import os
import psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute("SELECT 1;")
print(cur.fetchone())
conn.close()