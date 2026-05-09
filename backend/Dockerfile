# ── Stage 1: Install dependencies ──────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /backend

COPY requirements.txt .
RUN pip install --no-cache-dir --user --timeout 120 -r requirements.txt

# ── Stage 2: Runtime image ─────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /backend

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy application source
COPY app.py .
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