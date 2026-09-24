# Starts the local Parking Bot dashboard: http://127.0.0.1:8765
# Run: powershell -ExecutionPolicy Bypass -File dashboard\start.ps1
# First run installs the Python/Node dependencies and builds the frontend.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv\Scripts\python.exe"
$frontend = Join-Path $PSScriptRoot "frontend"

if (-not (Test-Path $python)) {
    Write-Host "Creating Python environment (.venv)..." -ForegroundColor Cyan
    python -m venv (Join-Path $root ".venv")
    & $python -m pip install -q -r (Join-Path $PSScriptRoot "backend\requirements.txt")
}

if (-not (Test-Path (Join-Path $frontend "dist\index.html"))) {
    Write-Host "Building frontend..." -ForegroundColor Cyan
    Push-Location $frontend
    try {
        if (-not (Test-Path "node_modules")) { npm install --silent }
        npm run build
    } finally { Pop-Location }
}

Start-Job { Start-Sleep 2; Start-Process "http://127.0.0.1:8765" } | Out-Null
& $python (Join-Path $PSScriptRoot "backend\app.py")
