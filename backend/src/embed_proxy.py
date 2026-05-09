# embed_proxy.py
# Embedding generation is not used in this deployment.
# The /chat endpoint handles embedding=None gracefully by proceeding
# with tool-orchestration context + DeepSeek LLM only.
# If the client supplies an embedding in the request body it will be used directly.
import logging

def get_embedding(query: str):
    logging.debug("embed_proxy: no local embedding model configured; returning None")
    return None