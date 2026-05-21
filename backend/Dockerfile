# ── Stage 1: Install Python dependencies ───────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /backend

COPY requirements.txt .
RUN pip install --no-cache-dir --user --timeout 120 -r requirements.txt

# ── Stage 2: Download ONNX embedding model (baked in; no runtime download) ─
# Model: sentence-transformers/all-MiniLM-L6-v2 (384-dim, ~23 MB)
# Downloaded once at build time — zero startup latency, works fully offline.
# To swap model: change the URLs below and rebuild. The embed_proxy.py
# implementation handles both pooled and non-pooled ONNX exports.
FROM python:3.11-slim AS model_downloader

RUN apt-get update && apt-get install -y --no-install-recommends wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /models

RUN wget -q --retry-connrefused --waitretry=5 --tries=3 \
    "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx" \
    -O model.onnx

RUN wget -q --retry-connrefused --waitretry=5 --tries=3 \
    "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json" \
    -O tokenizer.json

# ── Stage 3: Runtime image ──────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /backend

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
# Ensure Python resolves user site-packages even in minimal/non-interactive envs
ENV PYTHONPATH=/root/.local/lib/python3.11/site-packages

# Copy baked-in ONNX model and tokenizer from model_downloader stage
COPY --from=model_downloader /models/ ./src/models/

# libpq5  — runtime shared-library dependency for psycopg2-binary's bundled .so
# curl    — used by the healthcheck in docker-compose.yml
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy application source
COPY app.py .
COPY seed_admin.py .
COPY src/ ./src/
COPY config.yaml .
COPY config/ ./config/

# Copy migrations and runner (needed by entrypoint)
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/

# Copy entrypoint
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]