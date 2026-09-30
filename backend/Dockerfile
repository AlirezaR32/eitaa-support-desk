# syntax=docker/dockerfile:1
# ---------- Eitaa Support Desk :: backend ----------
# Python 3.12-slim, non-root, healthcheck-ready.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# system deps (libpq is bundled in asyncpg wheels; curl for healthcheck)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# python deps (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app code
COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

# non-root user + writable upload dir
RUN useradd --create-home --uid 10001 desk \
    && mkdir -p /data/uploads \
    && chown -R desk:desk /data /app
USER desk

ENV UPLOADS_DIR=/data/uploads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -sf http://127.0.0.1:8000/health || exit 1

# default: run migrations then start the API (single-process; sync worker in-process).
# For scale-out, run a second container with the same image and
# RUN_SYNC_WORKER=true / WEB run with RUN_SYNC_WORKER=false.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
