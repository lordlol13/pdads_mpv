# ============================================
# Stop all services
# Windows PowerShell
# ============================================

Write-Host "Stopping all PD.ADS MVP services..." -ForegroundColor Red

# Stop Docker containers
Write-Host "`nStopping Docker containers..." -ForegroundColor Yellow
docker stop pdads-postgres pdads-redis 2>$null
Write-Host "Docker containers stopped" -ForegroundColor Green

# Stop Celery processes
Write-Host "`nStopping Celery Worker..." -ForegroundColor Yellow
taskkill /F /IM python.exe 2>$null

Write-Host "`nAll services stopped!" -ForegroundColor Green

Pause
