web: uvicorn app.backend.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
worker: celery -A news_brain worker --loglevel=info
beat: celery -A news_brain beat --loglevel=info
