# KubeFinOps - local development launcher (Windows PowerShell).
# API on http://127.0.0.1:8000 (SQLite + built-in demo cluster), UI on http://localhost:5173.
# For the full stack use docker compose (deploy/docker-compose.yml) or a kind cluster (deploy/scripts/up.ps1).

Write-Host "KubeFinOps - local development launcher" -ForegroundColor Cyan

$env:Path = "C:\Program Files\nodejs;$env:AppData\npm;" + $env:Path

# Free ports 8000 and 5173 if a previous run is still listening.
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}

Write-Host "Starting API on http://127.0.0.1:8000 ..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$PSScriptRoot/backend'; python -m pip install -q -r requirements.txt; python run_backend.py"

Write-Host "Starting UI on http://localhost:5173 ..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:Path = 'C:\Program Files\nodejs;$env:AppData\npm;' + `$env:Path; Set-Location '$PSScriptRoot/frontend'; if (-not (Test-Path node_modules)) { npm ci }; npm run dev"

Write-Host ""
Write-Host "UI:       http://localhost:5173" -ForegroundColor Green
Write-Host "API docs: http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "Sign in as admin@kubefinops.localhost - the password is in backend/.env (created on first run)." -ForegroundColor Green
