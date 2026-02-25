# embed_proxy.py
import logging

try:
    from fastembed import TextEmbedding
    # Use a standard 384-dimensional model supported by fastembed
    embedding_model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
    logging.info("FastEmbed model loaded successfully.")
except Exception as e:
    embedding_model = None
    logging.error(f"FastEmbed init failed: {e}")

def get_embedding(query: str):
    if not embedding_model:
        logging.error("Embedding model not ready")
        return None
    try:
        # Generate 384-dim embedding locally
        return list(embedding_model.embed([query]))[0].tolist()
    except Exception as e:
        logging.error(f"Error generating local embedding: {e}")
        return None

# Test block
if __name__ == "__main__":
    test_query = "What does economics mean?"
    embedding = get_embedding(test_query)
    if embedding:
        print(f"Embedding for '{test_query}':\n{embedding}")
        print(f"Length: {len(embedding)}")
    else:
        print("Failed to get embedding.")