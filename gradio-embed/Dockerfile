FROM python:3.11-slim

WORKDIR /gradio-embed

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY embed.py .

EXPOSE 7860

CMD ["python", "embed.py"]