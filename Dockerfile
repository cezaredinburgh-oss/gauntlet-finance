# Gauntlet Finance — single service: API + built React UI
# Railway/Render: set env vars from Setup wizard → Deploy step (never bake secrets into the image).

FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
# Production UI talks to same origin (API serves the SPA)
ENV VITE_API_BASE=
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    APP_ENV=production \
    PORT=8020

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Optional: copy Bank statements fixtures (not secrets)
# COPY "Bank statements" /app/Bank statements

EXPOSE 8020
CMD uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-8020}
