FROM python:3.12-slim
WORKDIR /app
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt
COPY vouch ./vouch
COPY data/vendors.json data/injections.json ./data/
ENV VOUCH_DB=/data/vouch.db VOUCH_ENV=prod PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
# SQLite = single writer: run exactly ONE replica (see deploy/azure.md)
CMD ["uvicorn", "vouch.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
