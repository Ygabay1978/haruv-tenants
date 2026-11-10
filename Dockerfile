FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 portal && mkdir /data && chown portal /data
COPY receipts.py receipt_docs.py server.py storage.py import_data.py tenant_summary.py portal_rules.py notice_mail.py attachments.py telemetry.py directory_update.py services.py notice_reads.py notice_format.py ./
COPY static ./static
USER portal
ENV PORT=8080 PORTAL_DB=/data/portal.sqlite3
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 30 server:app"]
