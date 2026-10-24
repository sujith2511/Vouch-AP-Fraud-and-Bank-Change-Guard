FROM python:3.12-slim
WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
COPY vouch ./vouch
COPY data/vendors.json data/injections.json ./data/
# v2 seed inputs (so `python -m vouch.seed --dataset v2` works inside the container); demo_real_vendors.json is deliberately NOT copied
COPY data/v2/vendors.v2.json data/v2/payments.v2.jsonl data/v2/vendor_email_history.jsonl data/v2/emails.jsonl data/v2/emails.dev.jsonl data/v2/emails.holdout.jsonl ./data/v2/
ENV VOUCH_DB=/data/vouch.db VOUCH_ENV=prod PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/health')" || exit 1
# SQLite = single writer: run exactly ONE replica (see deploy/azure.md)
CMD ["uvicorn", "vouch.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
