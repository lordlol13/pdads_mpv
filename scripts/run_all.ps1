param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "start",
    [int]$BackendPort = 8889,
    [int]$FrontendPort = 3000,
    [switch]$NoMigrate,
    [switch]$NoBackend,
    [switch]$NoFrontend,
    [switch]$NoWorker,
    [switch]$NoBeat,
    [switch]$NoRedisCheck,
    [switch]$InstallFrontendDeps,
    [switch]$KillPortOwners,
    [switch]$OpenSeparateWindows
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDir = Join-Path $PSScriptRoot ".runtime"
$LogsDir = Join-Path $RuntimeDir "logs"
$StateFile = Join-Path $RuntimeDir "run_all_state.json"
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Write-Section {
    param([string]$Text)
    Write-Host "`n=== $Text ===" -ForegroundColor Cyan
}

function Ensure-Path {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -Path $Path -ItemType Directory | Out-Null
    }
}

function Get-ListeningPids {
    param([int]$Port)
    $items = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $items) {
        return @()
    }
    return @($items | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Wait-Port {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 40
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-ListeningPids -Port $Port).Count -gt 0) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Stop-PortOwners {
    param([int]$Port)
    $pids = Get-ListeningPids -Port $Port
    foreach ($processId in $pids) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
            Write-Host "Stopped PID $processId on port $Port"
        } catch {
            Write-Warning "Failed to stop PID ${processId} on port ${Port}: $($_.Exception.Message)"
        }
    }
}

function Reset-BeatScheduleFiles {
    Push-Location -LiteralPath $RepoRoot
    try {
        $files = @("celerybeat-schedule", "celerybeat-schedule.bak", "celerybeat-schedule.dat", "celerybeat-schedule.dir")
        $removed = @()
        foreach ($file in $files) {
            if (Test-Path -LiteralPath $file) {
                Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue
                $removed += $file
            }
        }
        if ($removed.Count -gt 0) {
            Write-Host "Reset beat schedule files: $($removed -join ', ')"
        }
    } finally {
        Pop-Location
    }
}

function Start-ServiceProcess {
    param(
        [string]$Name,
        [string]$Command
    )

    Ensure-Path -Path $RuntimeDir
    Ensure-Path -Path $LogsDir

    $ps = @"
`$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath '$RepoRoot'
$Command
"@

    if ($OpenSeparateWindows) {
        $windowPs = @"
`$Host.UI.RawUI.WindowTitle = 'pdads-$Name'
$ps
"@
        $proc = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", $windowPs -PassThru
        Write-Host "Started $Name in separate window (PID=$($proc.Id))"
        return $proc.Id
    }

    $stdoutLog = Join-Path $LogsDir ("{0}.out.log" -f $Name)
    $stderrLog = Join-Path $LogsDir ("{0}.err.log" -f $Name)

    $startArgs = @{
        FilePath = "powershell.exe"
        ArgumentList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $ps)
        WindowStyle = "Hidden"
        RedirectStandardOutput = $stdoutLog
        RedirectStandardError = $stderrLog
        PassThru = $true
    }
    $proc = Start-Process @startArgs

    Write-Host "Started $Name in background (PID=$($proc.Id))"
    Write-Host "  stdout: $stdoutLog"
    Write-Host "  stderr: $stderrLog"
    return $proc.Id
}

function Save-State {
    param([hashtable]$State)
    Ensure-Path -Path $RuntimeDir
    $StateJson = $State | ConvertTo-Json -Depth 6
    Set-Content -Path $StateFile -Value $StateJson -Encoding UTF8
}

function Load-State {
    if (-not (Test-Path -LiteralPath $StateFile)) {
        return @{}
    }
    try {
        $raw = Get-Content -Path $StateFile -Raw -Encoding UTF8
        if (-not $raw) {
            return @{}
        }
        $obj = $raw | ConvertFrom-Json
        $state = @{}
        foreach ($p in $obj.PSObject.Properties) {
            $state[$p.Name] = $p.Value
        }
        return $state
    } catch {
        Write-Warning "State file is unreadable, ignoring it."
        return @{}
    }
}

function Stop-From-State {
    $state = Load-State
    if ($state.Count -eq 0) {
        Write-Host "No saved process state found."
        return
    }

    foreach ($name in @("backend", "frontend", "worker", "beat", "redis")) {
        if (-not $state.ContainsKey($name)) {
            continue
        }
        $processId = 0
        try {
            $processId = [int]$state[$name]
        } catch {
            continue
        }

        try {
            $proc = Get-Process -Id $processId -ErrorAction Stop
            Stop-Process -Id $proc.Id -Force -ErrorAction Stop
            Write-Host "Stopped $name (PID=$processId)"
        } catch {
            Write-Host "$name PID=$processId is not running"
        }
    }

    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
}

function Show-Status {
    Write-Section "Port status"
    foreach ($port in @($BackendPort, $FrontendPort, 6379)) {
        $pids = Get-ListeningPids -Port $port
        if (@($pids).Count -gt 0) {
            Write-Host "Port ${port}: LISTEN by PID(s) $($pids -join ', ')"
        } else {
            Write-Host "Port ${port}: not listening"
        }
    }

    Write-Section "Saved process state"
    $state = Load-State
    if ($state.Count -eq 0) {
        Write-Host "No saved state"
        return
    }
    $state.GetEnumerator() | ForEach-Object {
        Write-Host "$($_.Key) = $($_.Value)"
    }

    if (Test-Path -LiteralPath $LogsDir) {
        Write-Section "Logs directory"
        Write-Host $LogsDir
    }
}

if ($Action -eq "status") {
    Show-Status
    exit 0
}

if ($Action -eq "stop") {
    Write-Section "Stopping services"
    Stop-From-State
    if ($KillPortOwners) {
        Stop-PortOwners -Port $BackendPort
        Stop-PortOwners -Port $FrontendPort
    }
    exit 0
}

if ($Action -eq "restart") {
    Write-Section "Restarting services"
    Stop-From-State
    if ($KillPortOwners) {
        Stop-PortOwners -Port $BackendPort
        Stop-PortOwners -Port $FrontendPort
    }
    $Action = "start"
}

Write-Section "Preflight checks"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python venv executable not found: $PythonExe"
}

if (-not $NoFrontend) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        throw "npm is not installed or not available in PATH"
    }
}

if (-not $NoRedisCheck) {
    $redisPids = Get-ListeningPids -Port 6379
    if (@($redisPids).Count -eq 0) {
        $redisCmd = Get-Command redis-server -ErrorAction SilentlyContinue
        if ($redisCmd) {
            Write-Host "Redis is not running. Starting redis-server..."
            $redisPid = Start-ServiceProcess -Name "redis" -Command "redis-server"
        } else {
            Write-Warning "Redis is not running on :6379 and redis-server is not in PATH. Celery may fail."
            $redisPid = $null
        }
    } else {
        Write-Host "Redis is already listening on :6379"
        $redisPid = $null
    }
} else {
    $redisPid = $null
}

if ($InstallFrontendDeps -and -not $NoFrontend) {
    Write-Section "Installing frontend dependencies"
    Push-Location -LiteralPath $RepoRoot
    try {
        npm install --prefix app/frontend
    } finally {
        Pop-Location
    }
}

if (-not $NoMigrate) {
    Write-Section "Running migrations"
    Push-Location -LiteralPath $RepoRoot
    try {
        & $PythonExe -m alembic upgrade head
    } finally {
        Pop-Location
    }
}

if ($KillPortOwners) {
    Write-Section "Freeing required ports"
    Stop-PortOwners -Port $BackendPort
    Stop-PortOwners -Port $FrontendPort
}

Write-Section "Starting services"
$stateToSave = @{
    started_at = (Get-Date).ToString("s")
}

if (-not $NoBackend) {
    $backendCmd = "& '$PythonExe' -m uvicorn app.backend.main:app --host 127.0.0.1 --port $BackendPort"
    $stateToSave.backend = Start-ServiceProcess -Name "backend" -Command $backendCmd
}

if (-not $NoWorker) {
    $workerCmd = "& '$PythonExe' -m celery -A app.backend.core.celery_app:celery_app worker --loglevel=info --pool=solo"
    $stateToSave.worker = Start-ServiceProcess -Name "worker" -Command $workerCmd
}

if (-not $NoBeat) {
    Reset-BeatScheduleFiles
    $beatCmd = "& '$PythonExe' -m celery -A app.backend.core.celery_app:celery_app beat --loglevel=info"
    $stateToSave.beat = Start-ServiceProcess -Name "beat" -Command $beatCmd
}

if (-not $NoFrontend) {
    $frontendCmd = "npm run dev --prefix app/frontend"
    $stateToSave.frontend = Start-ServiceProcess -Name "frontend" -Command $frontendCmd
}

if ($redisPid) {
    $stateToSave.redis = $redisPid
}

Save-State -State $stateToSave

Write-Section "Readiness"
if (-not $NoBackend) {
    if (Wait-Port -Port $BackendPort -TimeoutSeconds 60) {
        Write-Host "Backend is listening on http://127.0.0.1:$BackendPort"
    } else {
        Write-Warning "Backend did not open port $BackendPort in time"
    }
}

if (-not $NoFrontend) {
    if (Wait-Port -Port $FrontendPort -TimeoutSeconds 60) {
        Write-Host "Frontend is listening on http://127.0.0.1:$FrontendPort"
    } else {
        Write-Warning "Frontend did not open port $FrontendPort in time"
    }
}

Write-Section "Done"
Write-Host "Use: ./scripts/run_all.ps1 -Action status"
Write-Host "Use: ./scripts/run_all.ps1 -Action stop -KillPortOwners"
Write-Host "Use: ./scripts/run_all.ps1 -Action restart -OpenSeparateWindows  # optional old mode"
