# ============================================
# Остановка всех сервисов
# Для Windows PowerShell
# ============================================

Write-Host "🛑 Остановка всех сервисов PD.ADS MVP..." -ForegroundColor Red

# Остановка Docker контейнеров
Write-Host "`n🐳 Остановка Docker контейнеров..." -ForegroundColor Yellow
docker stop pdads-postgres pdads-redis 2>$null
Write-Host "✅ Docker контейнеры остановлены" -ForegroundColor Green

# Остановка Celery процессов
Write-Host "`n👷 Остановка Celery Worker..." -ForegroundColor Yellow
taskkill /F /IM python.exe 2>$null

Write-Host "`n✅ Все сервисы остановлены!" -ForegroundColor Green

Pause
