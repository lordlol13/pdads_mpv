# PD.ADS MVP - Start all services
# Windows PowerShell script

$ErrorActionPreference = "Stop"
$PROJECT_ROOT = "d:\программы\github_repository\pd.ads_MVP\pdads_mpv"
$VENV_PATH = "$PROJECT_ROOT\.venv\Scripts\Activate.ps1"

Write-Host "Starting PD.ADS MVP Pipeline...`n" -ForegroundColor Green

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& $VENV_PATH

# ============================================
# STAGE 1: Docker containers
# ============================================
Write-Host "`nSTAGE 1: Checking Docker containers..." -ForegroundColor Cyan

$POSTGRES_RUNNING = docker ps --filter "name=pdads-postgres" --format "{{.State}}" 2>$null
$REDIS_RUNNING = docker ps --filter "name=pdads-redis" --format "{{.State}}" 2>$null

if ($POSTGRES_RUNNING -ne "running") {
    Write-Host "Starting PostgreSQL..." -ForegroundColor Green
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
    Write-Host "PostgreSQL is running" -ForegroundColor Green
}

if ($REDIS_RUNNING -ne "running") {
    Write-Host "Starting Redis..." -ForegroundColor Green
    docker run -d `
        --name pdads-redis `
        -p 6379:6379 `
        redis:7
    Start-Sleep -Seconds 2
} else {
    Write-Host "Redis is running" -ForegroundColor Green
}

# ============================================
# STAGE 2: Database migrations
# ============================================
Write-Host "`nSTAGE 2: Running database migrations..." -ForegroundColor Cyan
Set-Location $PROJECT_ROOT
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "Migration error!" -ForegroundColor Red
    exit 1
}
Write-Host "Migrations completed" -ForegroundColor Green

# ============================================
# STAGE 3: Backend
# ============================================
Write-Host "`nSTAGE 3: Starting Backend server..." -ForegroundColor Cyan
Write-Host "Backend: http://localhost:8000" -ForegroundColor Yellow
Write-Host "Docs: http://localhost:8000/docs" -ForegroundColor Yellow
Start-Process powershell -ArgumentList `
    "-NoExit",`
    "-Command",`
    "cd '$PROJECT_ROOT'; & '$VENV_PATH'; python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8000 --reload"

Start-Sleep -Seconds 3

# ============================================
# STAGE 4: Celery Worker
# ============================================
Write-Host "`nSTAGE 4: Starting Celery Worker..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList `
    "-NoExit",`
    "-Command",`
    "cd '$PROJECT_ROOT'; & '$VENV_PATH'; python -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo"

Start-Sleep -Seconds 2

# ============================================
# STAGE 5: Celery Beat
# ============================================
Write-Host "`nSTAGE 5: Starting Celery Beat..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList `
    "-NoExit",`
    "-Command",`
    "cd '$PROJECT_ROOT'; & '$VENV_PATH'; python -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info"

Start-Sleep -Seconds 2

# ============================================
# STAGE 6: Frontend
# ============================================
Write-Host "`nSTAGE 6: Starting Frontend..." -ForegroundColor Cyan
Write-Host "Frontend: http://localhost:5173" -ForegroundColor Yellow
Start-Process powershell -ArgumentList `
    "-NoExit",`
    "-Command",`
    "cd '$PROJECT_ROOT\app\frontend'; npm run dev"

Write-Host "`nAll services started!`n" -ForegroundColor Green
Write-Host "Backend:  http://localhost:8000" -ForegroundColor Magenta
Write-Host "Frontend: http://localhost:5173" -ForegroundColor Magenta
Write-Host "Redis:    localhost:6379" -ForegroundColor Magenta
Write-Host "PostgreSQL: localhost:5432" -ForegroundColor Magenta
Write-Host "`nTo stop: .\stop-all-windows.ps1`n" -ForegroundColor Red

Pause
