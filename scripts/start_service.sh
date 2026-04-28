#!/bin/sh
set -eu

SERVICE_TYPE_VALUE="${SERVICE_TYPE:-}"
RAILWAY_SERVICE_VALUE="${RAILWAY_SERVICE_NAME:-}"

echo "SERVICE_TYPE = ${SERVICE_TYPE_VALUE}"
echo "RAILWAY_SERVICE_NAME = ${RAILWAY_SERVICE_VALUE}"

if [ -z "${SERVICE_TYPE_VALUE}" ]; then
  echo "[ERROR] SERVICE_TYPE is empty"
fi

# Fallback: infer service type from Railway service name when SERVICE_TYPE is not set.
if [ -z "${SERVICE_TYPE_VALUE}" ] && [ -n "${RAILWAY_SERVICE_VALUE}" ]; then
  case "${RAILWAY_SERVICE_VALUE}" in
    *worker*)
      SERVICE_TYPE_VALUE="worker"
      ;;
    *beat*)
      SERVICE_TYPE_VALUE="beat"
      ;;
    *)
      SERVICE_TYPE_VALUE="web"
      ;;
  esac
  echo "[INFO] SERVICE_TYPE inferred from RAILWAY_SERVICE_NAME: ${SERVICE_TYPE_VALUE}"
fi

if [ "${SERVICE_TYPE_VALUE}" = "worker" ] || [ "${SERVICE_TYPE_VALUE}" = "beat" ]; then
  echo "[DEBUG] validating celery import"
  python -c "from app.backend.core.celery_app import celery_app; print('[DEBUG] celery_app import ok:', celery_app.main)"
fi

case "${SERVICE_TYPE_VALUE}" in
  worker)
    echo "[INFO] starting Celery worker"
    exec celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --concurrency=2 --pool=solo
    ;;
  beat)
    echo "[INFO] starting Celery beat"
    exec celery -A app.backend.core.celery_app:celery_app beat --loglevel=info
    ;;
  web|"")
    if [ -z "${SERVICE_TYPE_VALUE}" ]; then
      echo "[ERROR] SERVICE_TYPE unresolved, defaulting to web"
    fi
    echo "[INFO] starting FastAPI (web)"
    exec uvicorn app.backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
    ;;
  *)
    echo "[ERROR] Unknown SERVICE_TYPE='${SERVICE_TYPE_VALUE}'"
    exit 1
    ;;
esac
