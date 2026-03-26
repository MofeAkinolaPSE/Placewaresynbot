

---

**Knowledge Retrieval API (inside SynBot)**
Purpose: **serve context to agents**

Runs as a **service module inside SynBot backend**.

Example structure:

```
synbot/
│
├── agents/
├── orchestration/
│
├── services/
│     knowledge_service.py
│
├── api/
│     retrieval_api.py
│
└── main.py
```

Agents and the **Executive Orchestrator System (EOS)** will call the retrieval service like this:

```
context = knowledge_service.search(query)
```

The service performs:

1. query embedding
2. vector search in pgvector
3. metadata filtering
4. returns best chunks

---

### 2️⃣ Runtime Flow in SynBot

```
User question
     ↓
Agent
     ↓
Knowledge Service
     ↓
Vector Search (pgvector)
     ↓
Top context chunks
     ↓
LLM reasoning
     ↓
Final answer
```

---

# SynBot Knowledge Retrieval API Service

Below is a **clean production version** designed for your architecture.

File:

```
synbot/services/knowledge_service.py
```

---

## knowledge_service.py

```python
import os
import psycopg2
from openai import OpenAI

# =====================================
# CONFIG
# =====================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DB_CONFIG = {
    "host": "localhost",
    "database": "synbot",
    "user": "postgres",
    "password": "password"
}

EMBEDDING_MODEL = "text-embedding-3-small"

client = OpenAI(api_key=OPENAI_API_KEY)

# =====================================
# DATABASE
# =====================================

def get_db():
    return psycopg2.connect(**DB_CONFIG)

# =====================================
# CREATE QUERY EMBEDDING
# =====================================

def create_query_embedding(query):

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query
    )

    return response.data[0].embedding

# =====================================
# VECTOR SEARCH
# =====================================

def vector_search(query_embedding, top_k=5):

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            content,
            metadata,
            1 - (embedding <=> %s) AS similarity
        FROM knowledge_chunks
        ORDER BY embedding <=> %s
        LIMIT %s
        """,
        (query_embedding, query_embedding, top_k)
    )

    results = cur.fetchall()

    cur.close()
    conn.close()

    return results

# =====================================
# METADATA FILTERED SEARCH
# =====================================

def search_with_filter(query_embedding, department=None, document_type=None, top_k=5):

    conn = get_db()
    cur = conn.cursor()

    filters = []
    params = []

    if department:
        filters.append("metadata->>'department' = %s")
        params.append(department)

    if document_type:
        filters.append("metadata->>'document_type' = %s")
        params.append(document_type)

    filter_clause = ""

    if filters:
        filter_clause = "WHERE " + " AND ".join(filters)

    params.extend([query_embedding, query_embedding, top_k])

    query = f"""
        SELECT
            content,
            metadata,
            1 - (embedding <=> %s) AS similarity
        FROM knowledge_chunks
        {filter_clause}
        ORDER BY embedding <=> %s
        LIMIT %s
    """

    cur.execute(query, params)

    results = cur.fetchall()

    cur.close()
    conn.close()

    return results

# =====================================
# MAIN RETRIEVAL FUNCTION
# =====================================

def search(query, top_k=5, department=None, document_type=None):

    query_embedding = create_query_embedding(query)

    if department or document_type:

        results = search_with_filter(
            query_embedding,
            department,
            document_type,
            top_k
        )

    else:

        results = vector_search(
            query_embedding,
            top_k
        )

    context = []

    for content, metadata, similarity in results:

        context.append({
            "content": content,
            "metadata": metadata,
            "similarity": similarity
        })

    return context
```

---

# Optional API Endpoint (FastAPI)

Agents may call this directly.

File:

```
synbot/api/retrieval_api.py
```

```python
from fastapi import APIRouter
from services.knowledge_service import search

router = APIRouter()

@router.post("/knowledge/search")
def knowledge_search(payload: dict):

    query = payload.get("query")
    department = payload.get("department")
    document_type = payload.get("document_type")
    top_k = payload.get("top_k", 5)

    results = search(
        query=query,
        department=department,
        document_type=document_type,
        top_k=top_k
    )

    return {"results": results}
```

---

# How SynBot Agents Use This

Example inside an agent:

```python
from services.knowledge_service import search

context = search(
    query="fumigation corrective actions",
    department="quality",
    top_k=5
)
```

Returned context:

```
[
  {
    content: "...corrective action text...",
    metadata: {document_type:"audit_report"},
    similarity: 0.92
  }
]
```

The agent feeds that into the LLM prompt.

---

# What This Gives SynBot

This service enables:

### Context-aware generation

Agents can reference:

* SOPs
* audit reports
* deviations
* maintenance records

---

### Department-level retrieval

```
search(query, department="finance")
```

---

### Document-type targeting

```
search(query, document_type="audit_report")
```

---

# Final SynBot Knowledge Architecture

```
Documents
    ↓
External Ingestion Script
    ↓
Chunks + Embeddings
    ↓
Postgres + pgvector
    ↓
Knowledge Service (inside SynBot)
    ↓
Agents + EOS
```

---

💡 One **extremely powerful improvement** I recommend next for SynBot is something called **Multi-Stage Retrieval (Enterprise RAG)**.

It improves answer accuracy **dramatically** by adding:

```
query rewriting
re-ranking
context compression
```

