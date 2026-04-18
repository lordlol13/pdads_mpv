# scripts/monitor_worker.ps1
$ErrorActionPreference = "Continue"
Write-Output "monitor_worker.ps1 starting..."
# Load DATABASE_URL from .env if present
$envFile = Join-Path $PSScriptRoot "..\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*DATABASE_URL\s*=\s*(.+)\s*$') {
            $val = $matches[1].Trim()
            $val = $val.TrimStart('"').TrimEnd('"').TrimStart("'").TrimEnd("'")
            $env:DATABASE_URL = $val
            Write-Output "Loaded DATABASE_URL from .env"
        }
    }
}
# Activate venv if present
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    & ".\.venv\Scripts\Activate.ps1"
}
Write-Output "Virtualenv activated (if present)."
$seen = @{}
while ($true) {
    Try {
        railway logs --service pdads_mpv_worker | Out-File -Encoding utf8 .\worker_logs_latest.txt
    } Catch {
        Write-Output "Failed to fetch railway logs: $_"
    }
    if (Test-Path .\worker_logs_latest.txt) {
        $lines = Get-Content .\worker_logs_latest.txt -ErrorAction SilentlyContinue
        foreach ($line in $lines) {
            if ($line -match 'ai_news_id=(\d+)') {
                $id = $matches[1]
                if (-not $seen.ContainsKey($id)) {
                    $seen[$id] = $true
                    $msg = "DETECTED_AI_NEWS_ID:$id"
                    Write-Output $msg
                    Write-Output $msg | Out-File -Append -Encoding utf8 .\pipeline_output.txt
                    # run DB check for user_feed for this ai_news id
                    Try {
                        python .\scripts\check_user_feed_db.py $id | Out-File -Append -Encoding utf8 .\pipeline_output.txt
                    } Catch {
                        Write-Output ("check_user_feed_db failed for id {0}: {1}" -f $id, $_) | Out-File -Append -Encoding utf8 .\pipeline_output.txt
                    }
                }
            }
        }
    }
    Start-Sleep -Seconds 30
}