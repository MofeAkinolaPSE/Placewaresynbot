import os
import asyncio
from dotenv import load_dotenv
from supabase import create_client, Client
from fastembed import TextEmbedding

# Load environment variables
load_dotenv()

# Setup Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL or SUPABASE_KEY not found in .env")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Check table count
try:
    print("Checking 'qna' table row count...")
    result = supabase.table("qna").select("*", count="exact").execute()
    # Depending on supabase client version, result.count might be int or None
    total = result.count
    if total is None:
         total = len(result.data)
    print(f"Total rows in 'qna': {total}")
    
    # Peek at first row
    if result.data:
        first_row = result.data[0]
        emb = first_row.get("embedding") # May be str or list
        if emb:
             print(f"First row embedding explicit length: {len(emb)}")
        else:
             print("First row has NO embedding")

except Exception as e:
    print(f"Error checking table count: {e}")

# Setup Embeddings
print("Loading embedding model...")
try:
    # Match the model in embed_proxy.py
    embedding_model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
    print("Model loaded.")
except Exception as e:
    print(f"Error loading model: {e}")
    exit(1)

def get_embedding(query: str):
    return list(embedding_model.embed([query]))[0].tolist()

def test_retrieval():
    query = "What does Placeware do?"
    print(f"\nGeneratig embedding for: '{query}'")
    
    embedding = get_embedding(query)
    print(f"Embedding generated. Length: {len(embedding)}")
    
    match_threshold = -1.0 # Very low to capture everything
    match_count = 5

    payload = {
        "query_embedding": embedding,
        "match_threshold": match_threshold,
        "match_count": match_count,
    }

    print(f"\nCalling supabase.rpc('match_documents', threshold={match_threshold}, count={match_count})...")
    
    try:
        response = supabase.rpc("match_documents", payload).execute()
        rows = response.data
        if not rows:
             print("No rows returned from match_documents even with negative threshold.")
        else:
            print(f"\nRows returned: {len(rows)}")
            for i, row in enumerate(rows):
                print(f"\n--- Result {i+1} ---")
                print(f"Similarity: {row.get('similarity', 'N/A')}")
                # print(f"Question: {row.get('question', 'N/A')}")
                # print(f"Answer: {row.get('answer', 'N/A')}")
            
    except Exception as e:
        print(f"RPC Error: {e}")

if __name__ == "__main__":
    test_retrieval()
