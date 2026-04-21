# AI-Driven Personalized News Feed

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green)
![Celery](https://img.shields.io/badge/Celery-Distributed-orange)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue)

Кратко: персонализированная платформа новостей с асинхронным пайплайном, обработкой через Celery и интеграцией LLM.

---

## Содержание

- [Быстрый старт](#быстрый-старт)
- [Запуск сервисов](#запуск-сервисов)
- [Инжест (парсер)](#инжест-parser)
  - [Ручной запуск](#ручной-запуск)
  - [Dry-run (без записи в БД)](#dry-run)
  - [Показать примеры (samples)](#показать-примеры)
- [Продакшен-настройки по умолчанию](#продакшен-настройки-по-умолчанию)
- [Полезные скрипты](#полезные-скрипты)
- [Отладка и частые проблемы](#отладка-и-частые-проблемы)
- [Файлы и точки входа](#файлы-и-точки-входа)
- [Разработка и тестирование](#разработка-и-тестирование)

---

## Быстрый старт

1. Создайте и активируйте виртуальное окружение.

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

2. Скопируйте пример окружения и заполните переменные (обязательно `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, ключи LLM):

```powershell
Copy-Item .env.example .env
# отредактируйте .env
```

3. Примените миграции:

```bash
alembic upgrade head
```

4. Запустите backend:

```bash
uvicorn app.backend.main:app --reload
```

---

## Запуск сервисов

Celery worker:

```bash
python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo
```

Celery beat:

```bash
python -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info
```

Настройте процессы в продакшене через Supervisor / systemd / контейнеры, в зависимости от инфраструктуры.

Для локального тестирования Celery-тасков синхронно (без отдельного worker):

PowerShell:
```powershell
$env:CELERY_TASK_ALWAYS_EAGER = 'true'
python -c "from brain.tasks.pipeline_tasks import scheduled_feed_ingestion; print(scheduled_feed_ingestion())"
```

Bash:
```bash
CELERY_TASK_ALWAYS_EAGER=true python -c "from brain.tasks.pipeline_tasks import scheduled_feed_ingestion; print(scheduled_feed_ingestion())"
```

---

## Инжест (parser)

Парсер реализован в `app/backend/services/feed_fetcher.py`. Он поддерживает:
- чтение RSS (через `feedparser`)
- скрейпинг фронт-страниц и извлечение текста/изображений (BeautifulSoup, site_parsers)
- выбор лучшего изображения через `media_service.fetch_media_urls`
- запись в `raw_news` через `create_raw_news` (дедупликация по content_hash)

### Ручной запуск (пишет в БД)

```bash
python scripts/ingest_feeds.py
```

Требуется рабочая БД и корректные переменные окружения — команда создаст записи в `raw_news`.

### Dry-run (без записи в БД)

Для безопасной проверки создания полезен `scripts/dry_run_ingest.py` — он подменяет `create_raw_news` на заглушку и печатает найденные payload'ы:

```bash
python scripts/dry_run_ingest.py
```

### Показать примеры (up to 5 на домен)

Чтобы быстро просмотреть примеры, используйте:

```bash
python scripts/show_parsed_samples.py
```

Этот скрипт собирает и печатает до 5 записей с каждого парсированного домена (заголовок, URL, IMAGE, фрагмент).

---

## Продакшен-настройки по умолчанию

Значения, настроенные в парсере по умолчанию (prod‑ориентированные):

```
per_rss_limit = 30          # записей на RSS
per_site_limit = 100        # ссылок с фронт-страницы
RSS_CONCURRENCY = 16       # параллельная обработка RSS-статей
SITE_CONCURRENCY = 12      # параллельная обработка site-статей
```

Рекомендации:
- Настройте семафоры и размеры потоков в зависимости от CPU/памяти воркера.
- Внедрите per-domain rate‑limit, `ETag`/`If-Modified-Since` и храните `last_processed` для инкрементальных прогонов.

---

## Полезные скрипты

- `scripts/ingest_feeds.py` — ручной запуск инжеста в БД
- `scripts/dry_run_ingest.py` — dry-run (не пишет в БД)
- `scripts/show_parsed_samples.py` — показать примеры парсинга
- `scripts/README_INGEST.md` — устаревший вспомогательный файл (информация объединена сюда)

---

## Отладка и частые проблемы

- Убедитесь, что установлены зависимости: `feedparser`, `beautifulsoup4`.
- Если видите HTTP 429 / 403 — уменьшите частоту запросов или добавьте задержки; некоторые API (Wikimedia и т.п.) могут требовать User-Agent или ключи.
- `daryo.uz` иногда возвращает 301 редирект — парсер корректно обрабатывает абсолютные URL, но имейте в виду редиректы.
- Если dry-run выдаёт ошибки, проверьте, что скрипты корректно подменяют `create_raw_news` (они создают заглушку для безопасного выполнения).
- Для восстановления локальной БД смотрите: `trash/cleanup_20260419_134030` (резервные файлы).

---

## Файлы и точки входа

- Парсер: `app/backend/services/feed_fetcher.py`
- Site-specific правила: `app/backend/services/site_parsers.py`
- HTTP клиент: `app/backend/services/http_client.py`
- Инжест/дедупликация: `app/backend/services/ingestion_service.py`
- Celery: `app/backend/core/celery_app.py`, таски в `brain/tasks/`

---

## Разработка и тестирование

- Тесты: добавить unit-тесты для парсера (TODO). Пары задач в `tests/`.
- Форматирование и быстрая проверка синтаксиса:

```bash
python -m compileall .
```

---

Если хотите, я могу:
- запустить реальный инжест (при наличии рабочей БД), или
- расширить dry-run (увеличить лимиты / добавить источники), или
- сохранить результаты выборки в JSON/CSV для анализа.

Спасибо — если нужно, укратю/дополню README по специфике деплоя (Railway / Docker / systemd).
