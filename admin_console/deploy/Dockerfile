# NTXP Admin Console API + web panel. Build from the REPO ROOT:
#   docker build -f admin_console/deploy/Dockerfile -t ntxp-admin .
# Never reachable directly: oauth2-proxy sits in front (see docker-compose.yaml).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Code. scripts/google_workspace is the shared Google access layer (server/gws.py imports it).
COPY admin_console/ /app/admin_console/
COPY scripts/google_workspace/ /app/scripts/google_workspace/

RUN if [ -f /app/admin_console/server/requirements.txt ]; then \
        pip install -r /app/admin_console/server/requirements.txt; \
    else \
        pip install fastapi "uvicorn[standard]" python-multipart httpx google-auth google-api-python-client; \
    fi \
    && find /app -name "__pycache__" -type d -prune -exec rm -rf {} + \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ntxp \
    && mkdir -p /data \
    && chown -R ntxp:ntxp /app /data

# Analytics store (flags, baselines, audit). Mounted as a named volume by compose.
ENV NTXP_ADMIN_DB_PATH=/data/admin_intelligence.json
VOLUME ["/data"]

USER ntxp
EXPOSE 8080

# /api/health requires an owner header, so the health check is a plain TCP connect.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8080), 3).close()" || exit 1

CMD ["uvicorn", "admin_console.server.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
