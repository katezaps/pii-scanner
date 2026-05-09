# --- Build frontend ---
FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- Runtime ---
FROM python:3.11-slim AS runtime
WORKDIR /app

# System deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Copy source and install
COPY pyproject.toml ./
COPY src/ src/
COPY brokers/ brokers/
RUN pip install --no-cache-dir . && playwright install chromium

# Copy migrations (not needed for pip install)
COPY migrations/ migrations/

# Copy built frontend into a static directory
COPY --from=frontend-build /app/frontend/dist static/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
