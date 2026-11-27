# syntax=docker/dockerfile:1
# --- Web UI -----------------------------------------------------------------------------------------
FROM node:22.11.0-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- API / workers / MCP ----------------------------------------------------------------------------
FROM python:3.12.7-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    KT_DATA_DIR=/data KT_WEB_DIST_DIR=/app/web/dist KT_AUTO_CREATE_SCHEMA=false
WORKDIR /app/backend
COPY backend/pyproject.toml backend/README.md ./
COPY backend/kt ./kt
RUN pip install ".[postgres]"
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY demo /app/demo
COPY --from=web /web/dist /app/web/dist
RUN useradd --create-home --uid 10001 kt && mkdir -p /data && chown kt /data
USER kt
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && kt serve --host 0.0.0.0 --port 8000"]
