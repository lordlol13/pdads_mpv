web: uvicorn app.backend.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
worker: celery -A app.backend.core.celery_app worker --loglevel=info
beat: celery -A app.backend.core.celery_app beat --loglevel=info
