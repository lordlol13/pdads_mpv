Парсер новостей — краткое руководство
=================================

Коротко: инструкции по установке зависимостей, запуску Celery (worker / beat) и однократному запуску инжеста.

1) Установка зависимостей

PowerShell:
```powershell
& .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Bash / WSL:
```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

2) Настройка окружения

Скопируйте пример и отредактируйте переменные (в частности `DATABASE_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`):

```powershell
Copy-Item .env.example .env
# затем отредактируйте .env
```

3) Подготовка базы данных

Выполните миграции Alembic или восстановите резервную БД с нужной схемой:

```bash
alembic upgrade head
```

Если у вас есть локальный файл БД, можно восстановить его из: [trash/cleanup_20260419_134030](trash/cleanup_20260419_134030)

4) Однократный запуск инжеста (ручной)

Этот скрипт вызывает `ingest_many` и запишет найденные `raw_news` в БД.

```bash
# из корня репозитория
python scripts/ingest_feeds.py
```

5) Запуск Celery (worker + beat)

Откройте два терминала — в одном запустите worker, в другом beat:

```bash
python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo
```

```bash
python -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info
```

6) Dry-run / тестирование без выделенного Celery сервера

- Самый простой dry-run — запустить `scripts/ingest_feeds.py` (см. выше).
- Если нужно запустить Celery‑задачу синхронно, используйте режим eager:

PowerShell:
```powershell
$env:CELERY_TASK_ALWAYS_EAGER = 'true'
python -c "from brain.tasks.pipeline_tasks import scheduled_feed_ingestion; print(scheduled_feed_ingestion())"
```

Bash:
```bash
CELERY_TASK_ALWAYS_EAGER=true python -c "from brain.tasks.pipeline_tasks import scheduled_feed_ingestion; print(scheduled_feed_ingestion())"
```

7) Полезные точки входа в код

- Парсер и логика инжеста: [app/backend/services/feed_fetcher.py](app/backend/services/feed_fetcher.py)
- Site-specific правила: [app/backend/services/site_parsers.py](app/backend/services/site_parsers.py)
- CLI для ручного запуска: [scripts/ingest_feeds.py](scripts/ingest_feeds.py)

8) Продакшен-значения по умолчанию

В коде заданы продакшен-ориентированные значения по умолчанию для лимитов и параллелизма в парсере:

```
# per-feed entries (RSS): 30
# per-site links (frontpage): 100
# RSS article concurrency (semaphore): 16
# Site article concurrency (semaphore): 12
```

Перед запуском в продакшене убедитесь, что ресурс воркеров и сетевых квот подходят под эти значения.

Примечание: для записи в `raw_news` требуется рабочая БД с нужной схемой. Если хотите, могу запустить dry-run на 2–3 источниках — скажите, восстановлена ли у вас локальная база или включаем `CELERY_TASK_ALWAYS_EAGER=true` и пробуем.
