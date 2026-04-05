# 🌍 AI-Driven Personalized News Feed (TikTok for News)

![Python](https://img.shields.io/badge/Python-3.12-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green) ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15.0-blue) ![AI](https://img.shields.io/badge/AI-DeepSeek-orange)

## 📌 О проекте (Project Vision)
Информационный шум — главная проблема современных медиа. Этот проект представляет собой MVP интеллектуального новостного агрегатора, который решает эту проблему с помощью **мультиагентной ИИ-архитектуры**. 

Вместо классической выдачи одних и тех же статей всем пользователям, система работает как алгоритм TikTok: она анализирует сырые новости, классифицирует их по гео-привязке и срочности, а затем **автоматически переписывает текст** под конкретные интересы когорт пользователей (персон). 

> **Пример, в котором используется эта задача:** Если в городе проходит крупный технологический форум, система не просто выдаст сухую сводку. Инженер получит сгенерированную новость с акцентом на представленные архитектурные решения, а предприниматель — текст с фокусом на привлеченные инвестиции стартапов.

---

## ⚙️ Как работает архитектура (Core Pipeline)

Система разделена на независимые микросервисы для обеспечения масштабируемости и снижения затрат на API.

### 1. Ingestion & Classification (Левое полушарие мозга)
* Сырые данные попадают в `raw_news` через API или внешний ingestion-слой.
* В текущем MVP классификация и генерация сведены к стабильному backend-пайплайну. DeepSeek отвечает за переписывание и оценку, а отдельный Gemini-классификатор можно подключить позже как расширение.

> **Пример, в котором используется эта задача:** Поступает новость: "В Ташкенте сошел сель, перекрыта трасса". Сначала запись сохраняется как raw news, затем пайплайн готовит AI-версию и статус обработки для ленты.

### 2. Prompt Factory & Cohort Generation (Правое полушарие мозга)
* Чтобы не тратить токены на генерацию уникального текста для *каждого* пользователя (что убьет бюджет проекта), используется когортный подход.
* Тяжелая языковая модель (**DeepSeek**) получает сырую новость и системный промпт с требованием переписать ее для 2-3 ключевых аудиторий (например, "tech", "sports", "general").

> **Пример, в котором используется эта задача:** Новость о запуске нового стадиона в Андижане обрабатывается DeepSeek. Модель создает две записи в БД: одну с меткой `persona = sports` (про вместимость и газон), вторую с меткой `persona = economy` (про создание рабочих мест и стоимость контракта). 

### 3. Smart Feed Serving (Выдача пользователю)
* Бэкенд на **FastAPI** обрабатывает запросы пользователей.
* Алгоритм сопоставляет `location` пользователя и его `interests` (хранящиеся в формате JSONB) с обработанными новостями из базы данных.
* Формируется бесконечная лента, оптимизированная по скорости отклика (через асинхронный драйвер asyncpg).

> **Пример, в котором используется эта задача:** Когда пользователь открывает приложение, FastAPI делает быстрый SQL-запрос, который фильтрует таблицу готовых ИИ-новостей. Если у пользователя в JSONB интересах есть "спорт", алгоритм подтягивает именно спортивные версии текстов, игнорируя версии для финансистов.

---

## 🗄️ Схема Базы Данных (Database Schema)
Проект использует строгую реляционную модель **PostgreSQL** для предотвращения дублирования данных.

* `users`: Профили (геолокация, вектор интересов).
* `raw_news`: Сырые тексты из интернета + ИИ-оценка региона и срочности.
* `ai_news`: Сгенерированные вариации текстов привязанные к `raw_news_id` (FK).
* `user_feed`: Таблица связи для быстрой отдачи персонализированной ленты.
* `interactions`: Сбор метрик (лайки, время просмотра) для будущего обучения ML-моделей.

> **Пример, в котором используется эта задача:** Жесткие связи (Foreign Keys) с правилом `ON DELETE CASCADE` гарантируют, что если сырая новость удаляется из базы по истечении срока давности, все её сгенерированные AI-вариации и лайки от пользователей удаляются автоматически, сохраняя чистоту сервера.

---

## 🛠️ Технологический стек (Tech Stack)
* **Backend:** Python 3.12, FastAPI, Uvicorn
* **Database:** PostgreSQL, SQLAlchemy (Async), Alembic
* **AI Integration:** DeepSeek API for generation, Gemini API for review/enhancement, mock fallback for local runs
* **Environment:** python-dotenv, Virtual Environments (.venv)

## 🚀 MVP Startup
1. Create and activate the virtual environment.
2. Set `.env` values at minimum for `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, and `DEEPSEEK_API_KEY` if you want real generation.
3. Apply the database schema:
	```bash
	alembic upgrade head
	```
4. Seed demo data if needed:
	```bash
	psql -d news_mvp -f sql/seed_test_data.sql
	```
5. Start the API:
	```bash
	uvicorn app.backend.main:app --reload
	```
6. Start the Celery worker:
	```bash
	python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo
	```
7. Start Celery Beat (scheduler every 15 minutes):
	```bash
	python -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info
	```
## 🔐 Demo Access
* Email: `demo@example.com`
* Password: `Demo12345!`

## Notes for MVP
* `raw_news.content_hash` prevents duplicate ingestion.
* `ai_news` is unique by `(raw_news_id, target_persona)`.
* If `DEEPSEEK_API_KEY` is empty, the pipeline falls back to a safe mock generator.
* DeepSeek generates text in Uzbek, Gemini improves it and provides a second score.
* Combined score is used for quality loop: target score is 8.0, hard minimum is 7.0.
* If score is below target, the pipeline runs a second rewrite round before final decision.
* NewsAPI ingestion now pulls only the last 7 days, while items from the last 24 hours are prioritized first.
* AI-generated products (`ai_news` with text/image links) are automatically deleted after 7 days by Celery Beat cleanup.