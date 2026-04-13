# 🚀 Запуск полного Pipeline PD.ADS MVP

## ⚡ Быстрый старт (WINDOWS)

```powershell
# 1. Открой PowerShell в папке проекта
# 2. Выполни:
.\run-all-windows.ps1
```

**Что произойдет:**
1. ✅ Запустятся Docker контейнеры (PostgreSQL + Redis)
2. ✅ Выполнятся миграции БД
3. ✅ Откроются 5 новых окон PowerShell для:
   - Backend (uvicorn)
   - Celery Worker
   - Celery Beat
   - Frontend (Vite)

---

## ⚡ Быстрый старт (LINUX/MAC)

```bash
# 1. Открой терминал в папке проекта
# 2. Дай права на исполнение:
chmod +x run-all-linux.sh stop-all-linux.sh

# 3. Запусти:
./run-all-linux.sh
```

---

## 📚 Компоненты и порядок запуска

| № | Компонент | Порт | URL | Описание |
|---|-----------|------|-----|---------|
| 1 | **PostgreSQL** | 5432 | - | База данных |
| 2 | **Redis** | 6379 | - | Message Broker для Celery |
| 3 | **Backend** | 8000 | http://localhost:8000 | FastAPI сервер |
| 4 | **Celery Worker** | - | - | Обработка асинхронных задач |
| 5 | **Celery Beat** | - | - | Планировщик периодических задач |
| 6 | **Frontend** | 5173 | http://localhost:5173 | React Vite приложение |

---

## 🔧 Ручной запуск каждого компонента (если нужно)

### 1️⃣ Docker контейнеры

```bash
# PostgreSQL
docker run -d \
  --name pdads-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=5432 \
  -e POSTGRES_DB=ai_news_db \
  -p 5432:5432 \
  postgres:15

# Redis  
docker run -d \
  --name pdads-redis \
  -p 6379:6379 \
  redis:7
```

### 2️⃣ Миграции БД

```bash
# Активируй виртуальное окружение
source .venv/bin/activate  # или .\.venv\Scripts\Activate.ps1 на Windows

# Запусти миграции
python -m alembic upgrade head
```

### 3️⃣ Backend (FastAPI + Uvicorn)

```bash
python -m uvicorn app.backend.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

**Доступны:**
- 🌐 API: http://localhost:8000
- 📖 Swagger Docs: http://localhost:8000/docs
- 📘 ReDoc: http://localhost:8000/redoc

### 4️⃣ Celery Worker

```bash
python -m celery -A app.backend.core.celery_app:celery_app \
  worker \
  --loglevel=info \
  --pool=solo
```

**Обрабатывает:**
- 📰 Ингестию новостей
- 🤖 LLM обработку текстов
- 📊 Генерацию эмбеддингов

### 5️⃣ Celery Beat (Scheduler)

```bash
python -m celery -A app.backend.core.celery_app:celery_app \
  beat \
  --loglevel=info
```

**Расписание:**
- ⏰ Каждый час: `scheduled_ingestion` (получение новостей из API)
- 🧹 Каждый день: `scheduled_cleanup_ai_products` (очистка старых данных)

### 6️⃣ Frontend (React + Vite)

```bash
cd app/frontend

# Первый запуск - установи зависимости
npm install

# Запусти dev сервер
npm run dev
```

**Доступен:**
- 🎨 Frontend: http://localhost:5173

---

## ✅ Проверка что всё работает

### Backend ✔️
```bash
curl http://localhost:8000/api/health/live
```

### Redis ✔️
```bash
# В Python или Redis CLI
redis-cli ping
# Ответ: PONG
```

### PostgreSQL ✔️
```bash
psql -h localhost -U postgres -d ai_news_db
```

### Celery Worker ✔️
В логах worker должно быть:
```
[tasks]
  . app.backend.core.celery_app.brain.tasks.process_raw_news
  . app.backend.core.celery_app.brain.tasks.scheduled_ingestion
  . app.backend.core.celery_app.brain.tasks.scheduled_cleanup_ai_products

[2026-04-13 12:00:00,000: INFO/MainProcess] celery@HOSTNAME ready.
```

---

## 🛑 Остановка всех сервисов

### Windows
```powershell
.\stop-all-windows.ps1
```

### Linux/Mac
```bash
./stop-all-linux.sh
```

---

## 🐛 Troubleshooting

### ❌ "Redis connection refused"
```bash
# Проверь что Redis запущен и доступен
redis-cli ping
# Если не работает, перезапусти Docker контейнер:
docker restart pdads-redis
```

### ❌ "Database connection error"  
```bash
# Проверь что PostgreSQL запущен
psql -h localhost -U postgres
# Если не работает:
docker restart pdads-postgres
```

### ❌ "Port already in use"
```bash
# Найди процесс на порту (например 8000)
lsof -i :8000  # Linux/Mac
netstat -ano | findstr :8000  # Windows

# Убей процесс
kill -9 <PID>  # Linux/Mac
taskkill /PID <PID> /F  # Windows
```

### ❌ Celery Worker тут же выключается
```bash
# 1. Проверь что Redis запущен
redis-cli ping

# 2. Проверь .env переменные:
grep REDIS .env
grep CELERY .env

# 3. Запусти worker с debug логами:
python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=debug --pool=solo
```

---

## 📝 Файлы конфигурации

- **`.env`** - Переменные окружения (API ключи, URLs БД и т.д.)
- **`alembic.ini`** - Конфиг миграций БД
- **`app/backend/core/config.py`** - Конфиг приложения
- **`app/backend/core/celery_app.py`** - Конфиг Celery
- **`app/frontend/vite.config.ts`** - Конфиг Vite

---

## 🚀 Pipeline обработки новостей

```
1. NewsAPI Source
   ↓
2. raw_news таблица (ingestion)
   ↓
3. Celery Worker обработка:
   - LLM переписывание текста 
   - Генерация эмбеддингов
   - Сохранение в ai_news
   ↓
4. Frontend отображение в Feed
   ↓
5. User interactions (лайки, комментарии)
```

---

## 💾 Важные SQL команды

```sql
-- Проверить статус новостей
SELECT process_status, COUNT(*) FROM raw_news GROUP BY process_status;

-- Проверить количество ai_news
SELECT COUNT(*) FROM ai_news;

-- Очистить failed новости
DELETE FROM raw_news WHERE process_status = 'failed';
```

---

## 📞 Контакты поддержки

Если что-то не работает:
1. Проверь логи в каждом окне
2. Убедись что Docker, PostgreSQL, Redis запущены
3. Посмотри раздел Troubleshooting выше
