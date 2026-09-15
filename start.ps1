Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   Kubernetes FinOps & Cost-Optimization Dashboard - PowerShell Launcher" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# Ensure Node.js is in PATH
$env:Path = "C:\Program Files\nodejs;$env:AppData\npm;" + $env:Path

# Free up ports 8000 and 5173 if previously running
Get-NetTCPConnection -LocalPort 8000,5173 -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}

Write-Host "Starting Python FastAPI Backend on http://127.0.0.1:8000 ..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:Path = 'C:\Program Files\nodejs;$env:AppData\npm;' + `$env:Path; Set-Location '$PSScriptRoot/backend'; python -m pip install -r requirements.txt; python run_backend.py"

Write-Host "Starting React Frontend on http://localhost:5173 ..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:Path = 'C:\Program Files\nodejs;$env:AppData\npm;' + `$env:Path; Set-Location '$PSScriptRoot/frontend'; & 'C:\Program Files\nodejs\npm.cmd' run dev"

Write-Host ""
Write-Host "All services launched!" -ForegroundColor Green
Write-Host "Frontend Dashboard: http://localhost:5173" -ForegroundColor Green
Write-Host "Backend REST API Docs: http://127.0.0.1:8000/docs" -ForegroundColor Green
