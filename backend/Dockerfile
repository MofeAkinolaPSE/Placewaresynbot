FROM python:3.11-slim AS builder

WORKDIR /backend

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim

WORKDIR /backend

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY app.py .           
## Copy app.py to /backend
COPY src/ ./src/       
## Copy src folder to /backend/src
COPY config.yaml .     
## Copy config.yaml to /backend


EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]