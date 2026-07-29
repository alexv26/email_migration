# Runs the app on Windows: the rq worker and the web server as two
# processes, same idea as start_combined.sh (used on Render) but adapted
# for Windows, which can't run gunicorn or RQ's default forking worker.
#
# Reads config from a .env file in this directory (same keys as Render's
# env var group: APP_PASSWORD, ADMIN_PASSWORD, SESSION_SECRET, FERNET_KEY,
# REDIS_URL, plus the optional tuning ones). See WINDOWS_SELF_HOST.md.

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Write-Error ".env not found in this directory - see WINDOWS_SELF_HOST.md to create one."
    exit 1
}

# Load .env into THIS process's environment so both child processes below
# inherit it - python-dotenv's own load_dotenv() only affects the Python
# process it runs in, not sibling processes like rq worker.
Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $key, $value = $line -split "=", 2
    [System.Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), "Process")
}

if (-not $env:PORT) { $env:PORT = "8000" }
if (-not $env:REDIS_URL) { $env:REDIS_URL = "redis://localhost:6379" }

Write-Host "Starting rq worker (SpawnWorker - Windows has no fork())..."
$worker = Start-Process -FilePath "venv\Scripts\rq.exe" `
    -ArgumentList "worker", "--worker-class", "rq.SpawnWorker", "--url", $env:REDIS_URL, "default" `
    -PassThru -NoNewWindow

Write-Host "Starting web server on port $($env:PORT)..."
try {
    & "venv\Scripts\uvicorn.exe" webapp.app:app `
        --host 0.0.0.0 --port $env:PORT --proxy-headers --forwarded-allow-ips "*"
}
finally {
    Write-Host "Stopping rq worker..."
    Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue
}
