# Pinsure — RAG Pipeline & LLM Repair Briefing
## Fixing Underwriting Reports and Chatbot Conversation Handling

**Reference project:** Warebot (Placeware Nigeria AI — same team, production-deployed)  
**Target:** Pinsure Copilot agent reading this to fix both features  
**Scope:** Full diagnosis + implementation roadmap drawn from Warebot's battle-tested patterns  

---

## Root Cause Diagnosis (Why Your Reports Are Broken)

Before any code, understand the two distinct failure modes:

**Problem 1 — Underwriting reports are inconsistent, irrelevant, or single-sentence per section**

This is a **prompt engineering failure**, not a data failure. What is happening:
- The entire report (all sections) is generated in **one LLM call** with a single giant prompt
- The LLM has no idea which section it is writing — it produces filler prose that satisfies the prompt superficially
- There is no **per-section instruction** telling the LLM exactly what to write, what data to use, and what format to produce
- There is no **validation step** — the output is accepted regardless of quality
- The RAG knowledge base is either not injected into the report prompt, or injected as an undifferentiated blob
- There are no **past report baselines** to improve against

**Problem 2 — Chatbot is stateless and gives poor answers**

- The chatbot treats each message as a new context-free query
- RAG retrieval is likely happening with the raw user message as the embedding query — this has poor recall because users phrase things differently from how the knowledge base is written
- There is no **query rewrite** step before embedding
- There is no **LLM re-ranking** of retrieved chunks — the top-3 by cosine similarity are not always the top-3 by relevance
- Conversation history is not being injected into the LLM context — the bot "forgets" what was said 2 turns ago
- There is no **intent classification** — every question gets a "report-style" answer or every question gets a "conversational" answer, never the right one

---

## Section 1 — Understanding the Warebot RAG Pipeline

This is the working reference. Study this before implementing anything.

### 1.1 The Two-Table Knowledge Architecture

Warebot has two distinct vector tables:

```
qna (simple, fast)
├── question        TEXT   — source question text
├── answer          TEXT   — answer text
└── embedding       vector(384)  — pre-computed embedding of the question

knowledge_chunks (rich, for documents)
├── document_id     UUID → ingested_documents FK
├── chunk_index     INT    — position within document
├── content         TEXT   — chunk text (typically 300-500 chars)
├── metadata        JSONB  — department, doc_type, source_file, date
└── embedding       vector(384)  — computed at ingestion time
```

The `qna` table is seeded from a CSV with pre-computed embeddings (`seed_qna.py`). It covers the FAQ/product knowledge.

The `knowledge_chunks` table is populated at runtime when documents (SOPs, policy documents, compliance guidelines) are ingested via the document upload API.

**For Pinsure**, you need the equivalent:

```
pinsure_qna
├── question        TEXT
├── answer          TEXT
└── embedding       vector(384)

pinsure_knowledge_chunks
├── document_id     UUID → pinsure_ingested_documents FK
├── chunk_index     INT
├── content         TEXT
├── metadata        JSONB  — doc_type: "policy_wording"|"underwriting_guide"|"claim_procedure"
└── embedding       vector(384)

pinsure_ingested_documents
├── id              UUID
├── filename        TEXT
├── doc_type        TEXT
├── uploaded_by     UUID
├── processed       BOOL
└── created_at      TIMESTAMPTZ
```

### 1.2 The SQL Functions You Must Have

Without these, retrieval is impossible. Add to your migration files:

```sql
-- migration: 008_vector_search_functions.sql

-- Function 1: QnA similarity search
CREATE OR REPLACE FUNCTION match_documents(
    query_embedding vector(384),
    match_threshold FLOAT,
    match_count     INT
)
RETURNS TABLE (
    id       UUID,
    question TEXT,
    answer   TEXT,
    similarity FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT id, question, answer,
           1 - (embedding <=> query_embedding) AS similarity
    FROM pinsure_qna
    WHERE 1 - (embedding <=> query_embedding) > match_threshold
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;

-- Function 2: Knowledge chunk similarity search (for documents)
CREATE OR REPLACE FUNCTION match_knowledge_chunks(
    query_embedding  vector(384),
    match_threshold  FLOAT,
    match_count      INT,
    filter_department TEXT DEFAULT NULL,
    filter_doc_type  TEXT DEFAULT NULL
)
RETURNS TABLE (
    id          UUID,
    document_id UUID,
    chunk_index INT,
    content     TEXT,
    metadata    JSONB,
    similarity  FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT id, document_id, chunk_index, content, metadata,
           1 - (embedding <=> query_embedding) AS similarity
    FROM pinsure_knowledge_chunks
    WHERE 1 - (embedding <=> query_embedding) > match_threshold
      AND (filter_department IS NULL OR metadata->>'department' = filter_department)
      AND (filter_doc_type IS NULL OR metadata->>'doc_type' = filter_doc_type)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;
```

### 1.3 The Six-Stage RAG Pipeline (KnowledgeService)

This is the most important piece. Warebot's `KnowledgeService` runs retrieval in 6 stages. All 6 matter:

```
Stage 1: Memory check
  └─ Check synbot_memory for a cached answer with confidence >= 0.7
     If hit → return immediately (fastest path, no vector query)

Stage 2: Query rewrite
  └─ Send raw query to LLM with instruction: "expand with domain synonyms"
     "What is the deductible?" → "deductible excess policy amount claim reduction threshold"
     This dramatically improves recall when user phrasing ≠ document phrasing

Stage 3: Embed the REWRITTEN query
  └─ get_embedding(rewritten_query) → 384-float list
     Note: embed the REWRITTEN query, not the original

Stage 4: Broad vector search (top_k=20, low threshold=0.55)
  └─ match_knowledge_chunks(embedding, 0.55, 20)
     Cast a wide net — you will re-rank down later

Stage 5: LLM re-rank (top_k → 5)
  └─ Ask LLM to score each of the 20 chunks 0-10 for relevance
     Keep the top 5 by LLM score (not by cosine similarity)
     This is the key quality step — cosine similarity alone is not enough

Stage 6: Gap detection
  └─ If best_similarity < 0.55 after rewrite: log to knowledge_gaps table
     This lets admins see what questions are not covered by the knowledge base
```

Implement this as `src/services/knowledge_service.py` in Pinsure.

### 1.4 Document Chunking (How to Ingest Policy Documents)

When an underwriter uploads a policy document (PDF/DOCX), you must chunk it before embedding. Warebot's chunker uses overlapping 500-char windows:

```python
# src/services/document_ingestor.py
import re
from src.embed_proxy import get_embedding

CHUNK_SIZE = 500      # characters
CHUNK_OVERLAP = 50    # overlap prevents losing context at boundaries

def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks for embedding."""
    text = re.sub(r'\s+', ' ', text).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks

def ingest_document(document_id: str, text: str, metadata: dict, db) -> int:
    """Chunk, embed, and store a document. Returns number of chunks created."""
    chunks = chunk_text(text)
    rows = []
    for i, chunk in enumerate(chunks):
        embedding = get_embedding(chunk)
        if embedding is None:
            continue
        rows.append({
            "document_id": document_id,
            "chunk_index": i,
            "content": chunk,
            "metadata": metadata,   # {"doc_type": "policy_wording", "product_type": "auto"}
            "embedding": embedding,
        })
    if rows:
        db.table("pinsure_knowledge_chunks").insert(rows).execute()
    return len(rows)
```

**Critical:** Every policy product wording, underwriting guideline, claims procedure, and exclusion schedule must be ingested this way. These are what the underwriting report and chatbot draw from.

---

## Section 2 — Fixing the Chat Pipeline

### 2.1 The Working Warebot Chat Flow (study this carefully)

```
POST /chat  {question, embedding?, mode?, chat_session_id?}
│
├─ 1. get_embedding(question)              [ONNX local, 384-dim]
│
├─ 2. QnARetriever.retrieve(embedding, k=3)
│      └─ match_documents RPC → [(question, answer), ...]
│
├─ 3. KnowledgeService.search(question, top_k=3)
│      └─ full 6-stage pipeline → context string
│
├─ 4. Combine context layers (in this order):
│      │  a. COMPANY PROFILE CONTEXT (static, from config.yaml)
│      │  b. QnA retrieval hits (joined answer text)
│      │  c. Knowledge base chunks (joined content)
│      │  d. Live tool outputs (if orchestrator ran any tools)
│      └─ context = "\n\n".join(all layers)
│
├─ 5. Inject conversation history
│      └─ get_chat_history(user_id, limit=6)
│         Append to context as "--- Recent Conversation ---\nUser:...\nAssistant:..."
│
├─ 6. Intent classification
│      └─ _classify_query_intent(question)
│         Returns "report" or "conversational" based on keywords
│
├─ 7. Build instruction string
│      └─ _build_chat_instruction(mode, question)
│         "report" → structured format prompt
│         "conversational" → "1-2 sentences maximum"
│
├─ 8. LLM call
│      └─ llm.generate_response(context, question, instruction)
│
├─ 9. Post-process
│      ├─ _enforce_mode_tone() — strip irrelevant CTAs from internal answers
│      └─ append_disclaimer() — insurance disclaimer at end
│
└─ 10. Save to chat_history, return answer + sources
```

### 2.2 Implement in Pinsure: Chat Pipeline Module

Create `src/chat_pipeline.py`:

```python
# src/chat_pipeline.py
"""
Pinsure multi-stage chat pipeline.
Drop-in replacement for any single-call LLM chat handler.
"""
import logging
from src.constants import BOT_NAME, BOT_BRAND, INSURANCE_DISCLAIMER, EMBEDDING_DIM, MATCH_THRESHOLD, DEFAULT_TOP_K
from src.embed_proxy import get_embedding          # copy from Warebot
from src.retrieval import QnARetriever             # copy from Warebot
from src.services.knowledge_service import KnowledgeService   # implement per Section 1.3

_REPORT_KEYWORDS = [
    "report", "generate", "analyse", "analysis", "summary", "breakdown",
    "list all", "show all", "underwriting", "assessment", "risk report",
    "claim report", "policy report", "loss ratio", "portfolio overview",
]

retriever = QnARetriever(match_threshold=MATCH_THRESHOLD)


def _classify_intent(question: str) -> str:
    q = (question or "").lower()
    if any(kw in q for kw in _REPORT_KEYWORDS):
        return "report"
    return "conversational"


def _build_instruction(intent: str, role: str) -> str:
    base = (
        f"You are {BOT_NAME}, the AI assistant for {BOT_BRAND}. "
        "Use ONLY the provided context as source of truth. "
        "Do not invent policy terms, claim amounts, or regulatory statements not in the context. "
        "If information is unavailable, say so briefly. "
    )
    if intent == "report":
        return (
            base
            + "Generate a structured, data-backed response using headers and bullet points. "
            + "State key findings, risk indicators, and recommended actions. "
            + "Every claim must be supported by the provided context."
        )
    return (
        base
        + "Reply conversationally — 1 to 2 sentences unless more detail is genuinely needed. "
        + "Do NOT produce a structured report unless the user asked for one."
    )


def run_chat(
    question: str,
    user_id: str | None,
    role: str = "customer",
    llm=None,
    db=None,
) -> dict:
    """
    Full multi-stage chat pipeline.
    Returns {"answer": str, "sources": list}
    """
    # Stage 1: Embed query
    embedding = get_embedding(question)

    # Stage 2: QnA retrieval
    qna_results = []
    if embedding:
        qna_results = retriever.retrieve(embedding, k=DEFAULT_TOP_K)

    # Stage 3: Knowledge base retrieval (6-stage pipeline)
    kb_context = ""
    if llm:
        svc = KnowledgeService(llm=llm)
        kb_result = svc.search(question, document_type=None, agent="chat")
        kb_context = kb_result.context

    # Stage 4: Assemble context layers
    layers = []

    # 4a. Company profile (static anchor — prevents hallucination of company facts)
    layers.append(
        f"{BOT_BRAND} verified profile:\n"
        "Products: Auto Insurance, Health Insurance, Life Insurance, Property Insurance, Travel Insurance.\n"
        "Services: Policy issuance, Claims processing, Risk underwriting, Fraud detection.\n"
        "Regulatory: NAICOM licensed, Nigeria insurance market."
    )

    # 4b. QnA hits
    if qna_results:
        qna_text = "\n\n".join(f"Q: {q}\nA: {a}" for q, a in qna_results if a)
        layers.append(f"KNOWLEDGE BASE:\n{qna_text}")

    # 4c. Knowledge chunks
    if kb_context:
        layers.append(f"DOCUMENT KNOWLEDGE:\n{kb_context}")

    context = "\n\n".join(filter(None, layers))

    # Stage 5: Conversation history injection
    if user_id and db:
        try:
            history = db.table("pinsure_chat_history") \
                .select("question, answer") \
                .eq("user_id", user_id) \
                .order("created_at", desc=True) \
                .limit(6) \
                .execute()
            rows = list(reversed(history.data or []))
            if rows:
                hist_lines = []
                for h in rows:
                    hist_lines.append(f"User: {h.get('question', '')}")
                    hist_lines.append(f"Assistant: {h.get('answer', '')}")
                context += "\n\n--- Recent Conversation ---\n" + "\n".join(hist_lines)
        except Exception as e:
            logging.warning("Chat history inject failed: %s", e)

    # Stage 6: Intent classification → instruction
    intent = _classify_intent(question)
    instruction = _build_instruction(intent, role)

    # Stage 7: LLM generation
    answer = ""
    if llm:
        answer = llm.generate_response(
            context=context,
            question=question,
            instruction=instruction,
        )

    if not answer:
        answer = f"I don't have enough information to answer that. Please contact {BOT_BRAND} support."

    # Stage 8: Append disclaimer
    answer = f"{answer}\n\n---\n*{INSURANCE_DISCLAIMER}*"

    # Stage 9: Save history
    if user_id and db:
        try:
            db.table("pinsure_chat_history").insert({
                "user_id": user_id,
                "question": question,
                "answer": answer,
                "sources": [{"q": q, "a": a} for q, a in qna_results],
            }).execute()
        except Exception as e:
            logging.warning("Chat history save failed: %s", e)

    sources = [{"question": q, "answer": a} for q, a in qna_results]
    return {"answer": answer, "sources": sources}
```

### 2.3 Add pinsure_chat_history Table

```sql
-- migration: 009_chat_history.sql
CREATE TABLE IF NOT EXISTS pinsure_chat_history (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID REFERENCES pinsure_users(id),
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    sources     JSONB DEFAULT '[]',
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON pinsure_chat_history (user_id, created_at DESC);
```

### 2.4 Update the /chat Endpoint

Replace whatever is in your `/chat` route body with a call to `run_chat()`:

```python
@app.post("/chat")
async def chat(request: Request):
    payload = verify_jwt(request, required=False)
    body = await request.json()
    question = str(body.get("question", "")).strip()[:2000]

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    user_id = (payload or {}).get("sub")
    role = ((payload or {}).get("roles") or ["customer"])[0]

    result = run_chat(
        question=question,
        user_id=user_id,
        role=role,
        llm=llm_client,   # your DeepSeek or unified_space_client instance
        db=db,
    )
    return result
```

---

## Section 3 — Fixing Underwriting Reports (Template-Driven Generation)

### 3.1 Why Section-by-Section Generation Is Non-Negotiable

When you send a 7-section report as one LLM prompt:
- The LLM satisfies the meta-instruction ("generate a report") by producing something that looks like 7 sections
- It doesn't have dedicated attention for each section
- It fills sections with generic text because it doesn't have a specific per-section instruction
- It runs out of "useful thought budget" by section 4-5 and degrades to single sentences

**Warebot's fix:** every section is a separate LLM call. Yes, this means 7 API calls instead of 1. The quality difference is night-and-day. This is exactly how Warebot's `ReportGenerationAgent` works.

### 3.2 Insurance Report Template Registry

Create `src/report_templates.py`:

```python
# src/report_templates.py
"""
Insurance report template registry for Pinsure.
Each template defines:
  - The ordered sections (separate LLM calls)
  - The scope fields required before generation
  - The DB tables to query for live data
  - Keywords for auto-detection from user requests
"""

from __future__ import annotations
from typing import Any, Dict, List

TEMPLATE_VERSION = "2026-05-18"


def _section(id_, title, prompt_hint, required=True, order=0):
    return {"id": id_, "title": title, "prompt_hint": prompt_hint,
            "required": required, "order": order}


def _scope_field(key, label, type_, required=False, options=None):
    d = {"key": key, "label": label, "type": type_, "required": required}
    if options:
        d["options"] = options
    return d


REPORT_TEMPLATE_REGISTRY: Dict[str, Dict[str, Any]] = {

    # ── Underwriting Assessment ───────────────────────────────────────────────
    "underwriting": {
        "client_facing_name": "Underwriting Assessment Report",
        "output_title": "Underwriting Assessment Report",
        "keywords": ["underwrite", "underwriting", "risk assessment", "risk score",
                     "policy assessment", "underwriting decision", "risk profile"],
        "tables": [
            {"table": "pinsure_policies", "select": "*", "order": "created_at", "limit": 1},
            {"table": "pinsure_underwriting_decisions", "select": "*", "order": "decided_at", "limit": 5},
        ],
        "scope_fields": [
            _scope_field("policy_id", "Policy ID / Application Number", "text", required=True),
            _scope_field("product_type", "Product Type", "select", required=True,
                         options=["auto", "health", "life", "property", "travel"]),
            _scope_field("applicant_name", "Applicant Name", "text"),
            _scope_field("sum_insured", "Sum Insured (₦)", "number"),
            _scope_field("custom_notes", "Underwriter Notes / Evidence", "text"),
        ],
        "sections": [
            _section("applicant_profile", "Applicant Risk Profile",
                     "Summarise the applicant's risk profile based on the provided data. "
                     "Include: product type, sum insured, applicant age/history if available, "
                     "prior claims if any. State the overall risk tier (Low/Medium/High).", order=1),
            _section("risk_factors", "Risk Factor Analysis",
                     "List all risk factors identified. For each factor: name, severity "
                     "(Low/Medium/High/Critical), contributing data point. "
                     "Group by category: financial risk, behavioural risk, asset risk, claims history risk. "
                     "Use bullet points with specific values from the data.", order=2),
            _section("ai_risk_score", "AI Risk Score & Rationale",
                     "State the computed risk score (0.0-1.0). Explain which factors contributed "
                     "most (top 3) and their individual weights. Reference the rule version used. "
                     "Compare score to product-type benchmarks if available in context.", order=3),
            _section("fraud_indicators", "Fraud Indicator Assessment",
                     "Assess any fraud signal flags from the context. State the fraud score (0.0-1.0). "
                     "List any triggered fraud signals with type and severity. "
                     "Recommend whether a manual fraud review is needed (Yes/No/Conditional).", order=4),
            _section("pricing_recommendation", "Premium & Pricing Recommendation",
                     "Based on the risk score and product type, recommend: base premium, "
                     "risk loading %, final recommended premium (₦), and deductible level. "
                     "State whether a standard/substandard/declined loading applies.", order=5),
            _section("underwriting_decision", "Underwriting Decision",
                     "State the clear decision: APPROVE / DECLINE / REFER WITH CONDITIONS. "
                     "If approving: state conditions, exclusions, or endorsements required. "
                     "If declining: state the specific grounds with policy/regulatory reference. "
                     "If referring: state what additional evidence is needed.", order=6),
            _section("compliance_note", "Regulatory & Compliance Note",
                     "Note any NAICOM, Insurance Act, or internal policy compliance requirements "
                     "that apply to this decision. Reference the applicable rule version.", order=7),
            _section("data_coverage", "Data Sources & Methodology",
                     "List the data sources used: tables queried, documents referenced via RAG, "
                     "fraud engine version, pricing engine version, rule set version.", order=8),
        ],
    },

    # ── Claims Investigation ──────────────────────────────────────────────────
    "claims_investigation": {
        "client_facing_name": "Claims Investigation Report",
        "output_title": "Claims Investigation Report",
        "keywords": ["claims report", "claim investigation", "claims analysis",
                     "claim assessment", "claims review", "claim status report"],
        "tables": [
            {"table": "pinsure_claims", "select": "*", "order": "created_at", "limit": 50},
            {"table": "pinsure_fraud_signals", "select": "*", "order": "flagged_at", "limit": 50},
        ],
        "scope_fields": [
            _scope_field("date_from", "Period From", "date", required=True),
            _scope_field("date_to", "Period To", "date", required=True),
            _scope_field("product_type", "Product Type", "select",
                         options=["All", "auto", "health", "life", "property", "travel"]),
            _scope_field("status_filter", "Status Filter", "select",
                         options=["All", "under_review", "approved", "rejected", "fraud_check", "paid"]),
            _scope_field("custom_notes", "Context / Adjuster Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "State: total claims in period, total amount claimed (₦), total approved (₦), "
                     "approval rate (%), average settlement time (days). Overall claims health posture.", order=1),
            _section("claims_log", "Claims Status Register",
                     "Table view of all claims: Claim #, Policy #, Incident Date, Type, "
                     "Amount Claimed, Amount Approved, Status, Days Open, Adjuster. "
                     "Flag overdue claims (>14 days in review).", order=2),
            _section("fraud_analysis", "Fraud & Anomaly Analysis",
                     "List all claims with fraud_score > 0.4. For each: "
                     "Claim #, fraud score, triggered signals (type + severity), recommended action. "
                     "State total fraud exposure amount.", order=3),
            _section("rejection_analysis", "Rejection & Decline Analysis",
                     "Analyse rejected claims: common rejection reasons, % by reason category, "
                     "any pattern that suggests SOP gaps or systemic issues.", order=4),
            _section("loss_ratio_analysis", "Loss Ratio Analysis",
                     "Calculate loss_ratio = total_claims_approved / total_premium_in_force. "
                     "Break down by product type. Flag any product line with loss_ratio > 0.65 as high risk.", order=5),
            _section("recommendations", "Recommendations",
                     "Minimum 4 specific, actionable recommendations: "
                     "fraud prevention, settlement efficiency, SOP updates, staffing. "
                     "Prioritise by impact.", order=6),
            _section("data_coverage", "Data Sources & Methodology",
                     "Tables queried, date range, total records analysed, rule versions.", order=8),
        ],
    },

    # ── Policy Portfolio Overview ─────────────────────────────────────────────
    "portfolio": {
        "client_facing_name": "Policy Portfolio Overview",
        "output_title": "Policy Portfolio Overview Report",
        "keywords": ["portfolio", "policy portfolio", "book of business",
                     "active policies", "portfolio overview", "policy summary"],
        "tables": [
            {"table": "pinsure_policies", "select": "*", "order": "created_at", "limit": 200},
            {"table": "pinsure_portfolio_snapshots", "select": "*", "order": "snapshot_date", "limit": 12},
        ],
        "scope_fields": [
            _scope_field("date_from", "Period From", "date"),
            _scope_field("date_to", "As At Date", "date", required=True),
            _scope_field("product_type", "Product Type", "select",
                         options=["All", "auto", "health", "life", "property", "travel"]),
            _scope_field("custom_notes", "Notes", "text"),
        ],
        "sections": [
            _section("executive_summary", "Executive Summary",
                     "Total policies in force, total premium (₦), average sum insured, "
                     "new policies this period, lapsed/cancelled policies.", order=1),
            _section("portfolio_breakdown", "Portfolio Breakdown by Product",
                     "Table: Product Type | Active Policies | Total Premium (₦) | Avg Premium | Loss Ratio | Trend. "
                     "Highlight fastest growing and highest risk product lines.", order=2),
            _section("renewal_pipeline", "Renewal Pipeline",
                     "Policies expiring in 30/60/90 days. Total premium at risk. "
                     "Retention rate from prior period renewals.", order=3),
            _section("risk_concentration", "Risk Concentration Analysis",
                     "Geographic concentration, customer concentration (top 10 accounts by premium). "
                     "Flag any single customer > 10% of portfolio.", order=4),
            _section("recommendations", "Recommendations",
                     "Growth opportunities, retention actions, risk diversification steps.", order=5),
            _section("data_coverage", "Data Sources & Methodology", "", order=6),
        ],
    },
}


def detect_report_type(text: str) -> str:
    """Return the best-match report type key from user text, or 'underwriting' as default."""
    text_lower = (text or "").lower()
    scores: dict[str, int] = {}
    for rtype, cfg in REPORT_TEMPLATE_REGISTRY.items():
        score = sum(1 for kw in cfg.get("keywords", []) if kw in text_lower)
        if score > 0:
            scores[rtype] = score
    if not scores:
        return "underwriting"
    return max(scores, key=lambda k: scores[k])


def get_template(report_type: str) -> dict:
    return REPORT_TEMPLATE_REGISTRY.get(report_type, REPORT_TEMPLATE_REGISTRY["underwriting"])
```

### 3.3 The Report Generation Agent

Create `src/agents/report_generation_agent.py`. This is the core fix — section-by-section generation with validation:

```python
# src/agents/report_generation_agent.py
"""
Section-by-section report generation agent for Pinsure.
Each section is generated by an independent, focused LLM call.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

from src.report_templates import detect_report_type, get_template, TEMPLATE_VERSION
from src.constants import BOT_NAME, BOT_BRAND, INSURANCE_DISCLAIMER

logger = logging.getLogger(__name__)


class ReportGenerationAgent:

    def __init__(self, llm, db):
        self._llm = llm
        self._db = db

    def generate(
        self,
        intent_text: str,
        report_type: str | None = None,
        scope_params: dict | None = None,
        actor_id: str | None = None,
    ) -> dict:
        """
        Main entry point. Returns:
        {
            "full_report": str (markdown),
            "report_type": str,
            "quality_score": float,
            "section_results": list[dict],
        }
        """
        report_type = report_type or detect_report_type(intent_text)
        scope_params = scope_params or {}
        template = get_template(report_type)

        # 1. Retrieve RAG context
        rag_context = self._retrieve_rag(intent_text, report_type)

        # 2. Pull live data from DB
        live_data = self._fetch_live_data(report_type, scope_params)

        # 3. Get past report baselines
        past_reports = self._get_past_reports(report_type)

        # 4. Build shared context blocks (assembled ONCE, injected into every section)
        rag_block = self._build_rag_block(rag_context)
        live_block = self._build_live_block(live_data)
        past_block = self._build_past_block(past_reports)
        scope_block = self._build_scope_block(scope_params)

        # 5. Generate each section independently
        sections = sorted(template.get("sections", []), key=lambda s: s["order"])
        section_results = []
        for sec in sections:
            content, confidence = self._generate_section(
                report_type=report_type,
                report_title=template["output_title"],
                sec_id=sec["id"],
                sec_title=sec["title"],
                hint=sec.get("prompt_hint", ""),
                required=sec.get("required", True),
                rag_block=rag_block,
                live_block=live_block,
                past_block=past_block,
                scope_block=scope_block,
                intent_text=intent_text,
            )
            status = "complete" if self._validate_section(sec["id"], content, sec.get("required", True)) else "incomplete"
            section_results.append({
                "section_id": sec["id"],
                "title": sec["title"],
                "content": content,
                "confidence_score": round(confidence, 2),
                "status": status,
                "order": sec["order"],
            })

        # 6. Assemble full report
        full_report = self._assemble(template["output_title"], report_type, section_results)

        # 7. Self-score
        quality_score = self._self_score(full_report, report_type)

        # 8. Persist if quality >= 7
        if quality_score >= 7.0:
            self._persist(report_type, intent_text, full_report, quality_score, actor_id)

        return {
            "full_report": full_report,
            "report_type": report_type,
            "quality_score": quality_score,
            "section_results": section_results,
            "template_version": TEMPLATE_VERSION,
        }

    # ── RAG retrieval ──────────────────────────────────────────────────────────
    def _retrieve_rag(self, query: str, report_type: str, k: int = 5):
        try:
            from src.embed_proxy import get_embedding
            from src.retrieval import QnARetriever
            from src.services.knowledge_service import KnowledgeService

            embedding = get_embedding(query)
            qna_hits = []
            if embedding:
                qna_hits = QnARetriever().retrieve(embedding, k=k)

            kb_result = KnowledgeService(llm=self._llm).search(
                query, document_type=self._doc_type_for_report(report_type), agent="report"
            )
            return qna_hits, kb_result.context
        except Exception as e:
            logger.warning("Report RAG failed: %s", e)
            return [], ""

    def _doc_type_for_report(self, report_type: str) -> str | None:
        mapping = {
            "underwriting": "underwriting_guide",
            "claims_investigation": "claim_procedure",
            "portfolio": "policy_wording",
        }
        return mapping.get(report_type)

    # ── Context block builders ─────────────────────────────────────────────────
    def _build_rag_block(self, rag_context) -> str:
        qna_hits, kb_text = rag_context if isinstance(rag_context, tuple) else ([], "")
        parts = []
        if qna_hits:
            parts.append("QNA KNOWLEDGE:\n" + "\n".join(f"Q: {q}\nA: {a}" for q, a in qna_hits if a))
        if kb_text:
            parts.append(f"DOCUMENT KNOWLEDGE:\n{kb_text}")
        return "\n\n".join(parts) if parts else ""

    def _build_live_block(self, live_data) -> str:
        if not live_data:
            return ""
        try:
            s = json.dumps(live_data, default=str, indent=2)
            if len(s) > 8000:
                s = s[:8000] + "\n... [truncated for token limit]"
            return f"LIVE DATABASE DATA:\n{s}"
        except Exception:
            return f"LIVE DATABASE DATA:\n{str(live_data)[:3000]}"

    def _build_past_block(self, past_reports) -> str:
        if not past_reports:
            return ""
        lines = []
        for i, p in enumerate(past_reports):
            lines.append(
                f"Previous report {i+1} (quality: {p.get('quality_score', 0)}/10): "
                f"{str(p.get('summary', ''))[:300]}"
            )
        return "PREVIOUS REPORTS (improve on these):\n" + "\n".join(lines)

    def _build_scope_block(self, scope_params: dict) -> str:
        if not scope_params:
            return ""
        lines = [f"  {k}: {v}" for k, v in scope_params.items() if v]
        return "REPORT SCOPE:\n" + "\n".join(lines) if lines else ""

    # ── Section generation ─────────────────────────────────────────────────────
    def _generate_section(
        self,
        report_type: str,
        report_title: str,
        sec_id: str,
        sec_title: str,
        hint: str,
        required: bool,
        rag_block: str,
        live_block: str,
        past_block: str,
        scope_block: str,
        intent_text: str,
    ) -> tuple[str, float]:
        """
        THIS IS THE CORE FIX.
        Each section gets a focused, independent LLM call.
        The prompt tells the LLM: "Write ONLY this one section."
        """
        prompt_parts = [
            f"You are {BOT_NAME}, the AI underwriting intelligence system for {BOT_BRAND} (insurance platform).",
            f"You are generating ONE SECTION of a {report_title}.",
            "",
        ]
        if scope_block:
            prompt_parts += [scope_block, ""]
        if rag_block:
            prompt_parts += [f"--- Policy & Regulatory Knowledge ---\n{rag_block}", ""]
        if past_block:
            prompt_parts += [f"--- {past_block} ---", ""]
        if live_block:
            prompt_parts += [f"--- {live_block} ---", ""]

        prompt_parts += [
            f'SECTION TO GENERATE NOW: "{sec_title}"',
            f"Section guidance: {hint}",
            "",
            f"Original request: {intent_text}",
            "",
            "STRICT INSTRUCTIONS:",
            f'- Write ONLY the content for the "{sec_title}" section.',
            "- DO NOT include the section heading — just the body content.",
            "- DO NOT write any other section.",
            "- Use specific values from the live data above. Do not invent numbers.",
            "- Use insurance-appropriate language (NAICOM standards).",
            "- Sub-headings (###), numbered lists, and **bold key figures** are encouraged.",
            "- Minimum 3 meaningful, data-backed sentences. Single sentences are unacceptable.",
            "- If a data point is genuinely unavailable, state 'Not available in current data' — do not fabricate.",
            "",
            "Begin the section content now:",
        ]

        prompt = "\n".join(prompt_parts)
        instruction = (
            f"You are {BOT_NAME}, a senior insurance analyst. "
            "Generate ONLY the requested report section. "
            "Use real data from the provided context. "
            "Be specific, professional, and data-backed. "
            "Minimum 3 sentences."
        )

        content = ""
        for attempt in range(2):
            try:
                content = self._llm.generate_response(
                    context="",
                    question=prompt,
                    instruction=instruction,
                ).strip()
                if self._validate_section(sec_id, content, required):
                    break
                logger.warning("Section %r failed validation (attempt %d)", sec_id, attempt + 1)
            except Exception as e:
                logger.warning("Section %r generation error: %s", sec_id, e)

        # Confidence heuristic: longer + more numbers = more confident
        num_count = len(re.findall(r"\d+(?:\.\d+)?%?", content))
        word_count = len(content.split())
        confidence = min(0.95, 0.4 + (word_count / 400) * 0.3 + min(num_count / 10, 1) * 0.25)
        return content, confidence

    def _validate_section(self, section_id: str, content: str, required: bool) -> bool:
        """Reject empty, too-short, or refusal responses."""
        if not content or len(content.strip()) < 80:
            return not required
        refusal_phrases = [
            "i cannot", "i'm unable", "i don't have", "no data available",
            "cannot generate", "not enough information", "i am unable",
        ]
        if any(p in content.lower() for p in refusal_phrases) and len(content) < 300:
            logger.warning("Section %r appears to be a refusal response", section_id)
            return not required
        return True

    # ── Assembly ───────────────────────────────────────────────────────────────
    def _assemble(self, report_title: str, report_type: str, sections: list[dict]) -> str:
        lines = [
            f"# {report_title}",
            f"**Generated:** {datetime.utcnow().strftime('%B %d, %Y at %H:%M UTC')}",
            f"**Report Type:** {report_type.replace('_', ' ').title()}",
            f"**Generated by:** {BOT_NAME} — {BOT_BRAND} Insurance Intelligence",
            "",
        ]
        for sec in sorted(sections, key=lambda s: s["order"]):
            lines.append(f"## {sec['title']}")
            if sec["status"] == "incomplete":
                lines.append("*[Section incomplete — insufficient data available.]*")
            elif sec["content"]:
                lines.append(sec["content"])
            lines.append(f"*Section confidence: {sec['confidence_score']:.0%}*")
            lines.append("")

        lines += [
            "---",
            f"*{INSURANCE_DISCLAIMER}*",
            f"*Template version: {TEMPLATE_VERSION}*",
        ]
        return "\n".join(lines)

    # ── Quality scoring ────────────────────────────────────────────────────────
    def _self_score(self, full_report: str, report_type: str) -> float:
        """Ask the LLM to score the report quality 1-10."""
        try:
            score_prompt = (
                f"You are a senior insurance report reviewer. "
                f"Score this {report_type} report from 1-10 on: "
                "specificity, data use, actionability, and completeness. "
                "Return ONLY a single number (e.g. '8'). Nothing else.\n\n"
                f"Report:\n{full_report[:3000]}"
            )
            raw = self._llm.generate_response(context="", question=score_prompt, instruction="")
            m = re.search(r"\b([0-9]|10)\b", raw or "")
            return float(m.group(1)) if m else 6.0
        except Exception:
            return 6.0

    # ── Persistence ────────────────────────────────────────────────────────────
    def _fetch_live_data(self, report_type: str, scope_params: dict) -> Any:
        template = get_template(report_type)
        rows = []
        try:
            for tbl_cfg in template.get("tables", []):
                tbl = tbl_cfg.get("table")
                sel = tbl_cfg.get("select", "*")
                lim = tbl_cfg.get("limit", 50)
                order_col = tbl_cfg.get("order")
                try:
                    q = self._db.table(tbl).select(sel).limit(lim)
                    if order_col:
                        q = q.order(order_col, desc=True)
                    if scope_params.get("date_from") and order_col:
                        q = q.gte(order_col, scope_params["date_from"])
                    if scope_params.get("date_to") and order_col:
                        q = q.lte(order_col, scope_params["date_to"])
                    if scope_params.get("policy_id"):
                        q = q.eq("id", scope_params["policy_id"])
                    if scope_params.get("product_type") and scope_params["product_type"] != "All":
                        q = q.eq("product_type", scope_params["product_type"])
                    rows.extend(q.execute().data or [])
                except Exception as e:
                    logger.warning("Live data fetch for table %r failed: %s", tbl, e)
        except Exception as e:
            logger.warning("Live data fetch failed: %s", e)
        return rows

    def _get_past_reports(self, report_type: str, limit: int = 3) -> list[dict]:
        try:
            res = self._db.table("pinsure_report_memory") \
                .select("summary, quality_score, created_at") \
                .eq("report_type", report_type) \
                .order("quality_score", desc=True) \
                .limit(limit) \
                .execute()
            return res.data or []
        except Exception:
            return []

    def _persist(self, report_type, intent_text, full_report, quality_score, actor_id):
        try:
            self._db.table("pinsure_report_memory").insert({
                "report_type": report_type,
                "intent_text": intent_text,
                "summary": full_report[:500],
                "full_report": full_report,
                "quality_score": quality_score,
                "actor_id": actor_id,
            }).execute()
        except Exception as e:
            logger.warning("Report memory persist failed: %s", e)
```

### 3.4 Add pinsure_report_memory Table

```sql
-- migration: 010_report_memory.sql
CREATE TABLE IF NOT EXISTS pinsure_report_memory (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    report_type     TEXT NOT NULL,
    intent_text     TEXT,
    summary         TEXT,
    full_report     TEXT,
    quality_score   NUMERIC(4,2),
    actor_id        UUID,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON pinsure_report_memory (report_type, quality_score DESC);
```

### 3.5 Wire Up the Underwriting Endpoint

```python
@app.post("/underwriting/reports/generate")
async def generate_underwriting_report(request: Request):
    verify_jwt(request)   # require underwriter or admin role
    body = await request.json()

    from src.agents.report_generation_agent import ReportGenerationAgent
    agent = ReportGenerationAgent(llm=llm_client, db=db)

    result = agent.generate(
        intent_text=body.get("intent_text", "generate underwriting report"),
        report_type=body.get("report_type"),    # optional override
        scope_params=body.get("scope_params", {}),
        actor_id=request.state.user.get("sub"),
    )
    return result
```

---

## Section 4 — RAG Ingestion Pipeline for Insurance Documents

### 4.1 The Ingestion Problem in Pinsure

The chatbot and underwriting agent are only as good as what is in the knowledge base. If your knowledge base is empty or contains only basic Q&A pairs, the LLM will hallucinate policy terms, clause numbers, and coverage limits.

**What must be ingested:**

| Document Type | `doc_type` tag | Used by |
|---|---|---|
| Policy wordings (auto, health, life, property) | `policy_wording` | Chatbot, underwriting |
| Underwriting guidelines | `underwriting_guide` | Underwriting report |
| Exclusion schedules | `exclusion_schedule` | Claims, chatbot |
| Claims procedure manual | `claim_procedure` | Claims agent, chatbot |
| NAICOM regulatory circulars | `regulatory` | Compliance, underwriting |
| Product pricing grids | `pricing_table` | Underwriting, recommendation |
| Fraud detection rules | `fraud_rules` | Claims investigation |

### 4.2 Document Ingestion API Endpoint

```python
@app.post("/admin/knowledge/ingest")
async def ingest_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    department: str = Form(default="underwriting"),
):
    """Upload and ingest a PDF/text document into the knowledge base."""
    require_role(request, "admin")

    # Read file content
    raw_bytes = await file.read()
    if len(raw_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # Extract text
    text = _extract_text(raw_bytes, file.filename)
    if not text or len(text.strip()) < 100:
        raise HTTPException(status_code=422, detail="Could not extract meaningful text from file")

    # Register document
    doc_id = str(uuid.uuid4())
    db.table("pinsure_ingested_documents").insert({
        "id": doc_id,
        "filename": file.filename,
        "doc_type": doc_type,
        "department": department,
        "uploaded_by": request.state.user.get("sub"),
        "processed": False,
    }).execute()

    # Chunk and embed
    from src.services.document_ingestor import ingest_document
    metadata = {"doc_type": doc_type, "department": department, "source_file": file.filename}
    chunk_count = ingest_document(doc_id, text, metadata, db)

    # Mark as processed
    db.table("pinsure_ingested_documents").update({"processed": True}).eq("id", doc_id).execute()

    return {"document_id": doc_id, "chunks_created": chunk_count, "filename": file.filename}


def _extract_text(raw_bytes: bytes, filename: str) -> str:
    """Extract plain text from PDF or text file bytes."""
    filename_lower = filename.lower()
    if filename_lower.endswith(".pdf"):
        try:
            import io
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logging.warning("PDF extraction failed: %s", e)
            return ""
    # Fallback: assume UTF-8 text
    try:
        return raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""
```

Add `pypdf==4.0.0` to `requirements.txt`.

### 4.3 QnA Seeding for Insurance Domain

Seed the `pinsure_qna` table with insurance-domain Q&A pairs. Format for the CSV:

```csv
question,answer,embedding
"What is the deductible for auto insurance?","The standard auto insurance deductible is ₦50,000 for third-party coverage and ₦100,000 for comprehensive coverage. Deductibles may vary by policy tier.","[0.123, ...]"
"How do I file a claim?","To file a claim: 1) Report the incident within 24 hours via the Pinsure portal or call 0800-PINSURE. 2) Complete the claim form with incident details. 3) Upload supporting documents (police report, photos, medical records). 4) A claims adjuster will contact you within 2 business days.","[0.456, ...]"
"What does comprehensive auto cover?","Comprehensive auto insurance covers: accidental damage, theft, fire damage, natural disasters, third-party bodily injury and property damage. It does not cover mechanical breakdown, deliberate acts, or driving under influence.","[0.789, ...]"
```

Generate the embeddings using the same ONNX model. Create `scripts/seed_qna.py` (copy from Warebot `backend/src/seed_qna.py`) and run it once against your data.

---

## Section 5 — Conversation Handling: The Memory System

### 5.1 The Warebot Memory Architecture (copy this)

Warebot has three levels of conversation memory:

```
Level 1: Turn-by-turn history (pinsure_chat_history)
  └─ Last 6 turns injected as "--- Recent Conversation ---" in context
  └─ This makes the bot remember what was said in THIS session

Level 2: Agent memory (cross-session pattern learning)
  └─ After high-quality answers, store the finding in synbot_memory
  └─ Stage 1 of KnowledgeService checks this before hitting the vector DB
  └─ Bot gets "smarter" over time for common questions

Level 3: Report memory (pinsure_report_memory)
  └─ Past reports with quality_score >= 7 are stored
  └─ Next report generation uses past reports as improvement baseline
```

For Pinsure, implement all three. You already have the DB tables from earlier migrations. The key one most apps miss is **Level 1** — injecting turn history into the LLM context.

### 5.2 The synbot_memory Pattern (Level 2)

```sql
-- migration: 011_agent_memory.sql
CREATE TABLE IF NOT EXISTS pinsure_agent_memory (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent       TEXT NOT NULL,
    topic       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    confidence  NUMERIC(4,3) DEFAULT 0.7,
    hit_count   INT DEFAULT 0,
    memory_type TEXT DEFAULT 'finding',   -- finding|pattern|recommendation
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON pinsure_agent_memory (agent, confidence DESC);
```

### 5.3 The Conversation Continuation Pattern

When a user asks a follow-up question ("What about the deductible?"), the chatbot must know what "that" refers to. This is only possible with history injection:

```python
# In run_chat(), BEFORE the LLM call:
# The history injection code (from Section 2.2) adds:
#
# --- Recent Conversation ---
# User: Can you explain comprehensive auto coverage?
# Assistant: Comprehensive auto insurance covers accidental damage, theft...
# User: What about the deductible?
#
# Now the LLM can resolve "What about the deductible?" to auto insurance deductibles.
```

Without this, every message is a cold start and the bot will give generic answers or ask "what are you referring to?".

---

## Section 6 — Query Rewrite for Insurance Domain

### 6.1 Why Query Rewrite Matters for Insurance

Users say: "I bumped into someone, what do I do?"  
Documents say: "Third-party liability claims procedure — bodily injury and property damage"

Without query rewrite, the embedding of "I bumped into someone" will not match the embedding of "third-party liability claims procedure". Vector distance will be too large → retrieval fails → LLM hallucinates.

With query rewrite, the LLM expands "I bumped into someone" to:  
`"third-party collision liability claim report procedure motor vehicle accident"`  
Now the embeddings match.

### 6.2 Insurance-Specific Query Rewrite Instruction

In `KnowledgeService._rewrite_query()`, replace the pharma instruction with:

```python
instruction = (
    "You are a query expansion assistant for an insurance company's policy and claims knowledge base. "
    "Your job is to rewrite the user's query using formal insurance terminology to improve document retrieval. "
    "Add relevant synonyms: e.g. 'accident' → 'accidental damage collision incident', "
    "'sick' → 'medical expenses hospitalisation health insurance claim', "
    "'car stolen' → 'vehicle theft comprehensive coverage police report'. "
    "Return ONLY the rewritten query string — no explanations, no bullet points. "
    "Maximum 20 words."
)
```

---

## Section 7 — The unified_space_client Compatibility Layer

The Pinsure report describes `unified_space_client.py` as the AI model interface. The Warebot equivalent is `src/deepseek.py`. Both must expose the same interface:

```python
def generate_response(self, context: str, question: str, instruction: str | None = None) -> str:
    """
    - context:     the RAG + live data string
    - question:    user's question OR a section prompt (for reports)
    - instruction: system message (overrides default)
    Returns: response text
    """
```

Verify that `unified_space_client.py` accepts these three arguments. If it uses a different signature (e.g., `prompt` instead of `question`), update the `ReportGenerationAgent` and `run_chat()` calls to match.

If `unified_space_client.py` calls an external HuggingFace Space, ensure it:
1. Has a **timeout** (30s) — HF Spaces can go cold
2. Has a **fallback** to DeepSeek if the Space is unavailable
3. Does NOT strip the `instruction` parameter — this is the system message and it must reach the model

---

## Section 8 — Environment Variables to Add

```env
# Knowledge base retrieval tuning
KNOWLEDGE_BROAD_TOP_K=20      # How many chunks to retrieve before re-ranking
KNOWLEDGE_FINAL_TOP_K=5       # How many chunks to keep after re-ranking  
KNOWLEDGE_GAP_THRESHOLD=0.55  # Below this similarity → log as knowledge gap
KNOWLEDGE_MEMORY_ENABLED=1    # Enable Stage 1 memory cache

# Report generation
REPORT_QUALITY_MIN=7          # Minimum quality score to persist a report
```

---

## Section 9 — Implementation Order (Do This Exactly)

Work in this sequence. Each step depends on the previous.

### Sprint 1 — Database Foundation (do first, unblocks everything)
1. Add `CREATE EXTENSION IF NOT EXISTS vector` to `000_core_schema.sql`
2. Create `pinsure_qna` table (migration 007 or next available number)
3. Create `pinsure_knowledge_chunks` + `pinsure_ingested_documents` tables (migration 008)
4. Create `match_documents` SQL function (migration 008)
5. Create `match_knowledge_chunks` SQL function (migration 008)
6. Create `pinsure_chat_history` table (migration 009)
7. Create `pinsure_report_memory` table (migration 010)
8. Create `pinsure_agent_memory` table (migration 011)

### Sprint 2 — Embedding & Retrieval
9. Copy `backend/src/embed_proxy.py` from Warebot verbatim → add ONNX model to Docker build
10. Copy `backend/src/retrieval.py` from Warebot → update table name to `pinsure_qna`
11. Implement `src/services/knowledge_service.py` (6-stage pipeline per Section 1.3)
12. Implement `src/services/document_ingestor.py` (chunking + embedding per Section 4.2)
13. Add `POST /admin/knowledge/ingest` endpoint

### Sprint 3 — Chat Pipeline
14. Implement `src/chat_pipeline.py` per Section 2.2
15. Update `/chat` endpoint to call `run_chat()` per Section 2.4
16. Test: send 5 messages in a row, verify conversation history is maintained

### Sprint 4 — Report Generation
17. Create `src/report_templates.py` with 3 templates (underwriting, claims_investigation, portfolio)
18. Implement `src/agents/report_generation_agent.py` per Section 3.3
19. Add `POST /underwriting/reports/generate` endpoint per Section 3.5
20. Test: generate an underwriting report, verify all 8 sections have meaningful content

### Sprint 5 — Content Seeding
21. Create `data/pinsure_qna.csv` with 30+ insurance Q&A pairs
22. Run `scripts/seed_qna.py` to populate `pinsure_qna`
23. Upload at least one policy wording PDF via `/admin/knowledge/ingest`
24. Verify retrieval works: embed a test query, check `match_documents` returns rows

---

## Section 10 — Common Failure Modes to Avoid

| Failure | Symptom | Fix |
|---|---|---|
| Embedding model not loaded | All chat answers are generic fallback | Check ONNX model path, run `docker build` with model_downloader stage |
| `match_documents` returns 0 rows | Context is always empty | (1) Check pgvector extension is installed. (2) Seed QnA table. (3) Verify embedding dimension matches (384). (4) Lower `MATCH_THRESHOLD` to 0.6 for testing |
| Single-sentence report sections | Report quality is poor | You are still generating the whole report in one call. Switch to section-by-section pattern |
| Bot forgets previous message | Every reply is context-free | History injection is missing. Add "--- Recent Conversation ---" block per Section 2.2 |
| Report has irrelevant content | LLM hallucinating | Scope params are not passed to the template. The `scope_block` must be the FIRST context block in every section prompt |
| Document ingestion uploads but no RAG hits | Documents ingested but not retrieved | Check that `processed=True` in `pinsure_ingested_documents`. Run raw SQL to verify `pinsure_knowledge_chunks` has rows |
| ReportGenerationAgent times out | 8 sections × 1 LLM call each = ~40s | Use `asyncio.gather` to run non-dependent sections concurrently. Or reduce to 5 sections for the MVP |

---

## Summary: The Three Root Fixes

1. **RAG is empty or bypassed** → Ingest policy documents. Add `match_knowledge_chunks`. Run the 6-stage KnowledgeService pipeline before every chat and report call.

2. **Reports are generated in one call** → Section-by-section generation with focused per-section prompts. Each section knows exactly what to write, what data to reference, and what format to use.

3. **Chatbot is stateless** → Inject last 6 turns of conversation history into every LLM call. The history sits in the context string AFTER the company profile and BEFORE the user's current question.

These three changes, applied in that order, will produce correct, consistent, data-backed underwriting reports and a chatbot that handles multi-turn conversations properly.

---

*This briefing was prepared from Warebot (Placeware Nigeria) — same codebase, patterns, and patterns in production.*  
*Warebot reference files: `backend/src/services/knowledge_service.py`, `backend/src/agents/report_generation_agent.py`, `backend/src/report_templates.py`, `backend/app.py` lines 4030–4145.*
