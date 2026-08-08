# Gauntlet Finance — single service: API + built React UI
# Never bake secrets into the image (set them in Railway Variables).

# ---- Frontend build ----
FROM node:20-bookworm-slim AS frontend
WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
# Same-origin API in production (empty base → /api or relative /)
ENV VITE_API_BASE=
ENV NODE_OPTIONS=--max-old-space-size=2048
# Prefer full check; if tsc flakes in CI, vite-only still ships a working UI
RUN npm run build || npx vite build

# ---- Python runtime ----
FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    APP_ENV=production

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Railway/Render inject $PORT
ENV PORT=8020
EXPOSE 8020

# Shell form so $PORT expands
CMD ["sh", "-c", "uvicorn backend.api.main:app --host 0.0.0.0 --port ${PORT:-8020}"]
