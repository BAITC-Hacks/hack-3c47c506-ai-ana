FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AUTH_DB_PATH=/app/data/auth/accounts.sqlite3

WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home app \
    && mkdir -p /app/data/auth \
    && chown app:app /app/data/auth \
    && chmod 0700 /app/data/auth

COPY backend/app ./app
COPY ["hackathon dataset anonymized .csv", "/app/hackathon dataset anonymized .csv"]

USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import json, urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); assert json.load(response)['status'] == 'ready'"]

# Only nginx can reach this port in Compose; it replaces incoming proxy headers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
