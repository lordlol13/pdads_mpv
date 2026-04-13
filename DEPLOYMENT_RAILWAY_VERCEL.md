# Vercel + Railway Deployment Guide (PR.ADS)

## 1) Target architecture

- `Vercel`: frontend from `app/frontend`
- `Railway` services:
1. `pdads_mpv` (FastAPI backend)
2. `pdads_mpv_worker` (Celery worker)
3. `pdads_mpv_beat` (Celery beat)
4. `psql` (PostgreSQL)
5. `redis` (Redis)

PostgreSQL stores app data. Redis is broker/backend cache for queue/results.

## 2) Railway services and start commands

Use the same repository for all 3 Python services.

`pdads_mpv` start command:

```bash
python -m uvicorn app.backend.main:app --host 0.0.0.0 --port ${PORT}
```

`pdads_mpv_worker` start command:

```bash
python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo
```

`pdads_mpv_beat` start command:

```bash
python -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info
```

## 3) Railway environment variables (important)

Set these for all backend-related services (`pdads_mpv`, `pdads_mpv_worker`, `pdads_mpv_beat`):

```bash
APP_ENV=production
DEBUG=false

DATABASE_URL=<Railway Postgres URL>
REDIS_URL=<Railway Redis URL db 0>
CELERY_BROKER_URL=<Railway Redis URL db 0>
CELERY_RESULT_BACKEND=<Railway Redis URL db 1>

JWT_SECRET_KEY=<strong random string>
SESSION_SECRET_KEY=<strong random string>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440

CORS_ALLOW_ORIGINS=https://<your-vercel-domain>,https://www.<your-vercel-domain>
TRUSTED_HOSTS=*

OAUTH_FRONTEND_SUCCESS_URL=https://<your-vercel-domain>
OAUTH_FRONTEND_ERROR_URL=https://<your-vercel-domain>

GOOGLE_OAUTH_CLIENT_ID=<google-client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<google-client-secret>

AUTH_DEBUG_RETURN_CODE=false
AUTH_VERIFICATION_CODE_TTL_MINUTES=10
AUTH_VERIFICATION_MAX_ATTEMPTS=5
PASSWORD_RESET_CODE_TTL_MINUTES=15
PASSWORD_RESET_MAX_ATTEMPTS=5

# choose one email provider
RESEND_API_KEY=<resend-key>
RESEND_FROM_EMAIL=<verified-sender>
# or SMTP_* values
```

Also add your AI/news keys (`OPENAI_API_KEY`, `NEWS_API_KEY`, etc.) if those features are used.

## 4) Database migrations

Run once after backend deploy:

```bash
python -m alembic upgrade head
```

## 5) Vercel frontend env

In Vercel Project -> Environment Variables:

```bash
VITE_API_BASE_URL=https://<your-railway-backend-domain>/api
```

Build settings:

- Root Directory: `app/frontend`
- Build Command: `npm run build`
- Output Directory: `dist`

## 6) Google OAuth setup

In Google Cloud Console (OAuth client):

Authorized redirect URI must include:

```text
https://<your-railway-backend-domain>/api/auth/oauth/google/callback
```

Authorized JavaScript origin should include your Vercel domain:

```text
https://<your-vercel-domain>
```

## 7) Verification and reset email reliability

For production:

- Keep `AUTH_DEBUG_RETURN_CODE=false`
- Ensure `RESEND_*` or `SMTP_*` is valid
- Verify sender domain/address

## 8) Final smoke checklist

After deploy, verify:

1. `GET https://<backend>/api/health/live` returns 200.
2. Register flow works: start -> verify code -> complete profile.
3. Forgot password works: send code -> reset -> login with new password.
4. Google button redirects and returns to frontend logged in.
5. Feed loads and actions work: like, save, share, comments.
6. Profile page opens and saved posts list works.

## 9) Ready-to-paste Railway AI prompt

Use this prompt in Railway assistant:

```text
Create deployment configuration for my Python monorepo app with 3 Railway services from one repo:
1) Web API service name: pdads_mpv
2) Celery worker service name: pdads_mpv_worker
3) Celery beat service name: pdads_mpv_beat

Project details:
- Backend entrypoint: app.backend.main:app
- Use uvicorn for web service on PORT env
- Use celery app: app.backend.core.celery_app:celery_app
- Worker command: python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo
- Beat command: python -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info
- Python dependencies from requirements.txt

Also connect these managed resources:
- PostgreSQL service (psql)
- Redis service (redis)

Set shared environment variables for all 3 services (with placeholders):
APP_ENV=production
DEBUG=false
DATABASE_URL=<postgres-url>
REDIS_URL=<redis-url-db0>
CELERY_BROKER_URL=<redis-url-db0>
CELERY_RESULT_BACKEND=<redis-url-db1>
JWT_SECRET_KEY=<strong-secret>
SESSION_SECRET_KEY=<strong-secret>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440
CORS_ALLOW_ORIGINS=https://<vercel-domain>,https://www.<vercel-domain>
TRUSTED_HOSTS=*
OAUTH_FRONTEND_SUCCESS_URL=https://<vercel-domain>
OAUTH_FRONTEND_ERROR_URL=https://<vercel-domain>
GOOGLE_OAUTH_CLIENT_ID=<client-id>
GOOGLE_OAUTH_CLIENT_SECRET=<client-secret>
AUTH_DEBUG_RETURN_CODE=false
AUTH_VERIFICATION_CODE_TTL_MINUTES=10
AUTH_VERIFICATION_MAX_ATTEMPTS=5
PASSWORD_RESET_CODE_TTL_MINUTES=15
PASSWORD_RESET_MAX_ATTEMPTS=5
RESEND_API_KEY=<resend-key>
RESEND_FROM_EMAIL=<from-email>

Finally add a one-time migration step command:
python -m alembic upgrade head

Return a concise deploy checklist and final service URLs.
```
