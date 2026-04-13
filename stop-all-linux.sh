#!/bin/bash
# ============================================
# Остановка всех сервисов
# Для Linux/Mac
# ============================================

echo "🛑 Остановка всех сервисов PD.ADS MVP..."

# Остановка Docker контейнеров
echo -e "\n🐳 Остановка Docker контейнеров..."
docker stop pdads-postgres pdads-redis 2>/dev/null || true

# Остановка Celery процессов
echo -e "\n👷 Остановка Celery процессов..."
pkill -f "celery.*worker" || true
pkill -f "celery.*beat" || true

echo -e "\n✅ Все сервисы остановлены!"
