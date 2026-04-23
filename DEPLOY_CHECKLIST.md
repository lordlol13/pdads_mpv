# Deploy checklist — быстрый план для деплоя

Ниже минимальные шаги, чтобы безопасно задеплоить проект (Railway/Vercel или Docker).

## 1) Локальная подготовка
- Скопируйте `.env.example` → `.env` и заполните секреты (не коммитьте `.env`).
- Убедитесь, что у вас установлены Docker и Docker Compose (если используете compose).

## 2) Сборка фронтенда (Vite)
```bash
cd app/frontend
npm ci
npm run build
# Установите VITE_API_BASE_URL в Vercel/окружении на https://<backend>/api
```

> На production обычно фронтенд размещается в Vercel, а бекенд отдельно (Railway). Dockerfile в проекте уже собирает фронтенд при создании образа.

## 3) Docker Compose (локальная прод-подобная среда)
```bash
# В корне проекта
cp .env.example .env    # заполните
docker compose up --build
```
- Порты: backend `http://localhost:8000`, frontend (если собран и включён) будет доступен как статические файлы в бекенде.

## 4) Миграции БД
После первого запуска (или при обновлении схемы):
```bash
# внутри контейнера web или в вашем venv
python -m alembic upgrade head
```

## 5) Railway / Production
- Настройте 3 сервиса в Railway (или аналог): `pdads_mpv` (web), `pdads_mpv_worker` (celery worker), `pdads_mpv_beat` (celery beat).
- В `pdads_mpv` в качестве команды запуска используйте (Railway):
```
python -m uvicorn app.backend.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'
```
- Worker:
```
python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo
```
- Beat:
```
python -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info
```
- Установите environment variables (см. `.env.example`) в Railway или CI secrets.

## 6) Проверки после деплоя
- Liveness: `GET https://<backend>/health` → 200
- Readiness: `GET https://<backend>/ready` → 200
- Swagger (если DEBUG=true): `https://<backend>/api/docs`
- Проверить, что Celery worker подключился (логи) и задачи идут в очередь.

## 7) Полезные команды
```bash
# Сборка образа и запуск одного контейнера (локально)
docker build -t pdads_mpv:latest .

docker run --env-file .env -p 8000:8000 pdads_mpv:latest

# Остановить compose
docker compose down -v
```

## 8) Советы
- Не передавайте секреты через репозиторий. Используйте Railway secrets / GitHub Secrets / Vault.
- Для production используйте managed Postgres и Redis (Railway), задав корректные `DATABASE_URL` и `REDIS_URL`.
- Запустите `python -m alembic upgrade head` как один из шагов post-deploy.

---
Если хотите, могу:
- добавить `docker-compose.prod.yml` с рекомендуемыми настройками для cloud
- подготовить `GitHub Actions` workflow для build → push → Docker Registry → deploy
- автоматически запустить локальный smoke-test (health/readiness)

### CI / GitHub Actions (быстрая настройка)

1. В репозитории создан workflow `.github/workflows/ci.yml` который:
	- собирает фронтенд (`npm ci && npm run build`),
	- устанавливает Python-зависимости и запускает `pytest`,
	- собирает Docker-образ и пушит в GHCR (`ghcr.io/${{ github.repository_owner }}/pdads_mpv`).

2. Нужные секреты/права:
	- `GITHUB_TOKEN` — уже доступен в Actions (но убедитесь, что в настройках репозитория разрешено `packages: write`).
	- Для Docker Hub используйте `DOCKERHUB_USERNAME` и `DOCKERHUB_PASSWORD` и измените workflow.

### Production compose

Добавлен `docker-compose.prod.yml` — используется для односерверного прод-развёртывания или тестов на VPS.
- Подставьте в `docker-compose.prod.yml` ваш `ghcr.io/<owner>/pdads_mpv:latest` или задайте переменные `WEB_IMAGE`/`WORKER_IMAGE`.
- Hints: используйте `.env` (не в репо) с `DATABASE_URL`/`REDIS_URL` и секретами.

---
Сделал оба шага: workflow и `docker-compose.prod.yml`. Следующие шаги, которые я могу выполнить:

- Настроить автодеплой в Railway (нужен `RAILWAY_API_KEY`), или
- Добавить GitHub Actions job, который автоматически деплоит на Railway/GCP/AWS.

Что предпочитаете дальше?