# Multi-stage Dockerfile: build frontend with Node, install Python deps, run FastAPI

### Stage 1: build frontend
FROM node:22 AS frontend_builder
WORKDIR /frontend
COPY app/frontend/package*.json ./
RUN npm ci --silent
COPY app/frontend ./
RUN npm run build --if-present

### Stage 2: install Python deps
FROM python:3.11-slim AS python_builder
WORKDIR /app
RUN apt-get update && apt-get install -y build-essential libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN python -m pip install --upgrade pip setuptools wheel
RUN python -m pip install --no-cache-dir -r requirements.txt

### Final image
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y libpq5 && rm -rf /var/lib/apt/lists/*

# copy installed python packages from builder
COPY --from=python_builder /usr/local /usr/local

# copy built frontend
COPY --from=frontend_builder /frontend/dist /app/app/frontend/dist

# copy project files
COPY . .

EXPOSE 8000

# ENTRYPOINT uses sh -c so Railway's startCommand (CMD override) can expand env vars.
# Default CMD runs FastAPI; Railway overrides CMD for worker/beat services via startCommand.
ENTRYPOINT ["sh", "-c"]
CMD ["uvicorn app.backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
