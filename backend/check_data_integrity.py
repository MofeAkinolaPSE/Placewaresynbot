import os
import sys
import logging
from dotenv import load_dotenv

# Ensure we can import from src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from src.db import db
from src.constants import TABLE_QNA
# We import seed function, but need to find where it is defined. 
# It was in seed_qna.py, but it uses relative imports.
# We'll just define logic here to keep it simple.
import csv
import json

logging.basicConfig(level=logging.INFO)

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "qna_pairs_with_embeddings.csv")

def check_qna_table():
    try:
        logging.info(f"Checking table '{TABLE_QNA}'...")
        res = db.table(TABLE_QNA).select("id", count="exact").execute()
        count = res.count
        logging.info(f"Existing rows: {count}")

        if count == 0:
            logging.info("Table is empty. Attempting to seed...")
            seed_data()
        else:
            logging.info("Table has data. No seed needed.")
        
        # Test Retrieval
        from src.embed_proxy import get_embedding
        emb = get_embedding("What does Placeware do?")
        if not emb:
            logging.error("Embedding generation failed.")
            return

        logging.info("Testing retrieval RPC...")
        payload = {
            "query_embedding": emb,
            "match_threshold": 0.5, # Lower threshold for test
            "match_count": 1
        }
        rpc_res = db.rpc("match_documents", payload).execute()
        if not rpc_res.data:
            logging.warning("Retrieval returned 0 results despite data existing. INDEX PROBABLY BROKEN.")
            logging.warning("Please run 'backend/migrations/019_fix_vector_index.sql' in Supabase dashboard.")
        else:
            logging.info(f"Retrieval success! Found: {rpc_res.data[0].get('question')}")

    except Exception as e:
        logging.error(f"Error checking QnA table: {e}")

def seed_data():
    if not os.path.exists(DATA_PATH):
        logging.error(f"Data file not found at {DATA_PATH}")
        return

    rows = []
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            emb_str = row.get("embedding")
            if not emb_str:
                continue
            try:
                emb = json.loads(emb_str)
                rows.append({
                    "question": row["question"],
                    "answer": row["answer"],
                    "embedding": emb
                })
            except:
                continue
    
    if rows:
        # Insert in chunks of 50
        chunk_size = 50
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i+chunk_size]
            db.table(TABLE_QNA).insert(chunk).execute()
        logging.info(f"Seeded {len(rows)} rows.")

if __name__ == "__main__":
    check_qna_table()
