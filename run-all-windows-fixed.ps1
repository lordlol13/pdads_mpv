# ============================================
# PD.ADS MVP - Полный запуск всех сервисов
# Для Windows PowerShell
# ============================================

$ErrorActionPreference = "Stop"
$PROJECT_ROOT = Split-Path -Parent $MyInvocation.MyCommandPath
$VENV_PATH = "$PROJECT_ROOT\.venv\Scripts\Activate.ps1"

Write-Host "Запуск PD.ADS MVP Pipeline...`n" -ForegroundColor Green

# Активируем виртуальное окружение
Write-Host "Активируем виртуальное окружение..." -ForegroundColor Yellow
& $VENV_PATH

# ============================================
# ЭТАП 1: Docker контейнеры (PostgreSQL + Redis)
# ============================================
Write-Host "`nЭТАП 1: Проверяем Docker контейнеры..." -ForegroundColor Cyan

$POSTGRES_RUNNING = docker ps --filter "name=pdads-postgres" --format "{{.State}}" 2>$null
$REDIS_RUNNING = docker ps --filter "name=pdads-redis" --format "{{.State}}" 2>$null

if ($POSTGRES_RUNNING -ne "running") {
    Write-Host "Запускаем PostgreSQL контейнер..." -ForegroundColor Green
    docker run -d `
        --name pdads-postgres `
        -e POSTGRES_USER=postgres `
        -e POSTGRES_PASSWORD=5432 `
        -e POSTGRES_DB=ai_news_db `
        -p 5432:5432 `
        -v pgdata:/var/lib/postgresql/data `
        postgres:15
    Start-Sleep -Seconds 3
} else {
    Write-Host "PostgreSQL уже запущен" -ForegroundColor Green
}

if ($REDIS_RUNNING -ne "running") {
    Write-Host "Запускаем Redis контейнер..." -ForegroundColor Green
    docker run -d `
        --name pdads-redis `
        -p 6379:6379 `
        redis:7
    Start-Sleep -Seconds 2
} else {
    Write-Host "Redis уже запущен" -ForegroundColor Green
}

# ============================================
# ЭТАП 2: Миграции БД
# ============================================
Write-Host "`nЭТАП 2: Запускаем миграции БД..." -ForegroundColor Cyan
Set-Location $PROJECT_ROOT
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "Ошибка миграции!" -ForegroundColor Red
    exit 1
}
Write-Host "Миграции завершены" -ForegroundColor Green

# ============================================
# ЭТАП 3: Backend (uvicorn)
# ============================================
Write-Host "`nЭТАП 3: Запускаем Backend сервер..." -ForegroundColor Cyan
Write-Host "Backend будет доступен на http://localhost:8000" -ForegroundColor Yellow
Write-Host "API документация: http://localhost:8000/docs" -ForegroundColor Yellow
Start-Process powershell -ArgumentList `
    "-NoExit",`
    "-Command",`
    "cd '$PROJECT_ROOT'; & '$VENV_PATH'; python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000 --reload"

Start-Sleep -Seconds 3

# ============================================
# ЭТАП 4: Celery Worker
# ============================================
Write-Host "`nЭТАП 4: Запускаем Celery Worker..." -ForegroundColor Cyan
Write-Host "Worker будет обрабатывать асинхронные задачи" -ForegroundColor Yellow
Start-Process powershell -ArgumentList `
    "-NoExit",`
    "-Command",`
    "cd '$PROJECT_ROOT'; & '$VENV_PATH'; python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo"

Start-Sleep -Seconds 2

# ============================================
# ЭТАП 5: Celery Beat (Scheduler)
# ============================================
Write-Host "`nЭТАП 5: Запускаем Celery Beat (Scheduler)..." -ForegroundColor Cyan
Write-Host "Beat будет запускать периодические задачи (ингестию новостей, cleanup)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList `
    "-NoExit",`
    "-Command",`
    "cd '$PROJECT_ROOT'; & '$VENV_PATH'; python -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info"

Start-Sleep -Seconds 2

# ============================================
# ЭТАП 6: Frontend (Vite)
# ============================================
Write-Host "`nЭТАП 6: Запускаем Frontend dev server..." -ForegroundColor Cyan
Write-Host "Frontend будет доступен на http://localhost:5173" -ForegroundColor Yellow
Start-Process powershell -ArgumentList `
    "-NoExit",`
    "-Command",`
    "cd '$PROJECT_ROOT\app\frontend'; npm run dev"

Write-Host "`nВСЕ СЕРВИСЫ ЗАПУЩЕНЫ!`n" -ForegroundColor Green
Write-Host "Backend:  http://localhost:8000" -ForegroundColor Magenta
Write-Host "Frontend: http://localhost:5173" -ForegroundColor Magenta
Write-Host "Redis:    localhost:6379" -ForegroundColor Magenta
Write-Host "PostgreSQL: localhost:5432" -ForegroundColor Magenta
Write-Host "`nДля остановки всех сервисов используй: stop-all-windows.ps1`n" -ForegroundColor Red

Pause
