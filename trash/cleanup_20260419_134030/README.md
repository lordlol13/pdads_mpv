Moved files and cleanup summary

These files and directories were moved to this folder by the automated cleanup run on 2026-04-19.

Moved items:
- .pytest_cache/
- .ruff_cache/
- ai_news.db
- app.log.1
- celerybeat-schedule.bak
- celerybeat-schedule.dat
- celerybeat-schedule.dir
- dev.db
- pytest-cache-files-0_srvuy6/
- pytest-cache-files-uxmtwg24/
- raw_token_line.txt
- resend_emails_error.txt
- resend_emails_fixed.json
- resend_emails_query_error.txt
- resend_emails_simple.json
- resend_history_brief.txt
- resend_matches_gmail.json
- resend_murod_error.txt
- resend_onboarding_error.txt
- resend_recipient_list.txt
- resend_response.json
- temp_test_img_v2_run.txt
- web_env_check.txt
- web_env_search.txt
- web_logs_filtered.txt
- web_logs_resend.txt
- web_logs_resend_search.txt
- web_logs_search.txt
- worker_logs_filtered.txt
- worker_logs_latest.txt
- worker_logs_search.txt
- __pycache__/

How to restore (PowerShell):

1) From repository root run (adjust cleanup folder name if different):

```powershell
$ts = 'cleanup_20260419_134030'
$trash = Join-Path (Get-Location) "trash\$ts"
Get-ChildItem -Path $trash -Recurse | ForEach-Object {
  $relative = $_.FullName.Substring($trash.Length).TrimStart('\')
  $dest = Join-Path (Get-Location) $relative
  if (-not (Test-Path (Split-Path $dest))) { New-Item -ItemType Directory -Path (Split-Path $dest) -Force | Out-Null }
  Move-Item -Path $_.FullName -Destination $dest -Force
}
```

2) After restoring, remove the cleanup folder or keep as backup.

If you want, I can restore specific files or perform a safe permanent deletion after you confirm.
