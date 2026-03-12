import os
import asyncio
from dotenv import load_dotenv
from src.db import db
import json

# Load environment variables
load_dotenv()

# Inspect stored embedding
try:
    print("Fetching one row from qna...")
    result = db.table("qna").select("*").limit(1).execute()
    if result.data:
        row = result.data[0]
        emb_str = row.get("embedding")
        print(f"Raw embedding type: {type(emb_str)}")
        if isinstance(emb_str, str):
            print(f"Raw string start: {emb_str[:50]}")
            emb_list = json.loads(emb_str)
            print(f"Parsed list length: {len(emb_list)}")
            print(f"First 5 elements: {emb_list[:5]}")
            
            # Check for zeros
            zeros = [x for x in emb_list if x == 0.0]
            print(f"Count of exact zeros: {len(zeros)}")
            
        elif isinstance(emb_str, list):
             print(f"Is list length: {len(emb_str)}")
             print(f"First 5: {emb_str[:5]}")
    else:
        print("Table qna is empty.")

except Exception as e:
    print(f"Error inspecting row: {e}")
