#!/bin/bash
# ============================================
# PD.ADS MVP - Полный запуск всех сервисов
# Для Linux/Mac
# ============================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$PROJECT_ROOT/venv/bin/activate"

echo -e "\n🚀 Запуск PD.ADS MVP Pipeline...\n" 

# Активируем виртуальное окружение
echo "📦 Активируем виртуальное окружение..." 
source "$VENV_PATH"

# ============================================
# ЭТАП 1: Docker контейнеры (PostgreSQL + Redis)
# ============================================
echo -e "\n🐳 ЭТАП 1: Проверяем Docker контейнеры..."

POSTGRES_RUNNING=$(docker ps --filter "name=pdads-postgres" --format "{{.State}}" 2>/dev/null || echo "")
REDIS_RUNNING=$(docker ps --filter "name=pdads-redis" --format "{{.State}}" 2>/dev/null || echo "")

if [ "$POSTGRES_RUNNING" != "running" ]; then
    echo "▶️  Запускаем PostgreSQL контейнер..."
    docker run -d \
        --name pdads-postgres \
        -e POSTGRES_USER=postgres \
        -e POSTGRES_PASSWORD=5432 \
        -e POSTGRES_DB=ai_news_db \
        -p 5432:5432 \
        -v pgdata:/var/lib/postgresql/data \
        postgres:15
    sleep 3
else
    echo "✅ PostgreSQL уже запущен"
fi

if [ "$REDIS_RUNNING" != "running" ]; then
    echo "▶️  Запускаем Redis контейнер..."
    docker run -d \
        --name pdads-redis \
        -p 6379:6379 \
        redis:7
    sleep 2
else
    echo "✅ Redis уже запущен"
fi

# ============================================
# ЭТАП 2: Миграции БД
# ============================================
echo -e "\n🗄️  ЭТАП 2: Запускаем миграции БД..."
cd "$PROJECT_ROOT"
python -m alembic upgrade head
echo "✅ Миграции завершены"

# ============================================
# ЭТАП 3-6: Запуск всех сервисов в фоне / новых окнах
# ============================================

# Backend (uvicorn)
echo -e "\n⚙️  ЭТАП 3: Запускаем Backend сервер..."
echo "💡 Backend будет доступен на http://localhost:8000"
gnome-terminal -- bash -c "cd '$PROJECT_ROOT'; source '$VENV_PATH'; python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000 --reload; exec bash" &
sleep 2

# Celery Worker
echo -e "\n👷 ЭТАП 4: Запускаем Celery Worker..."
echo "🔄 Worker будет обрабатывать асинхронные задачи"
gnome-terminal -- bash -c "cd '$PROJECT_ROOT'; source '$VENV_PATH'; python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo; exec bash" &
sleep 2

# Celery Beat
echo -e "\n⏰ ЭТАП 5: Запускаем Celery Beat (Scheduler)..."
echo "📅 Beat будет запускать периодические задачи..."
gnome-terminal -- bash -c "cd '$PROJECT_ROOT'; source '$VENV_PATH'; python -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info; exec bash" &
sleep 2

# Frontend
echo -e "\n🎨 ЭТАП 6: Запускаем Frontend dev server..."
echo "💡 Frontend будет доступен на http://localhost:5173"
gnome-terminal -- bash -c "cd '$PROJECT_ROOT/app/frontend'; npm run dev; exec bash" &

echo -e "\n\n✅ ВСЕ СЕРВИСЫ ЗАПУЩЕНЫ!\n"
echo -e "\033[35m📍 Backend:  http://localhost:8000\033[0m"
echo -e "\033[35m📍 Frontend: http://localhost:5173\033[0m"
echo -e "\033[35m📍 Redis:    localhost:6379\033[0m"
echo -e "\033[35m📍 PostgreSQL: localhost:5432\033[0m"
echo -e "\n\033[33m💡 Откроются новые окна терминала для каждого сервиса.\033[0m\n"
echo -e "\033[31m🛑 Для остановки всех сервисов используй: ./stop-all-linux.sh\033[0m\n"
