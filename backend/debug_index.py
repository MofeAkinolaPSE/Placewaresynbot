import os
import asyncio
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Setup Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# try to drop index
try:
    print("Dropping IVFFlat index...")
    # Cannot drop index via client easily unless SQL allowed.
    # But usually service_role key allows arbitrary SQL if running via SQL editor...
    # BUT via API? API allows RPC or Table ops.
    # PostgREST doesn't allow arbitrary SQL exec except via RPC.
    
    # Check if there is an RPC to execute SQL? Unlikely.
    pass
except Exception as e:
    print(e)

# Instead, try to retrieve without index?
# Postgres uses index if available.

# Let's try to match with threshold -1.0 ONE MORE TIME but checking if ANY embedding is NULL
try:
    res = supabase.table("qna").select("embedding").limit(1).execute()
    print(f"Embedding sample: {str(res.data[0]['embedding'])[:50]}...")
except Exception as e:
    print(e)
