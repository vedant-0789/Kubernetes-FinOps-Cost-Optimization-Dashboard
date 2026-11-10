@echo off
rem KubeFinOps - local development launcher (Windows cmd). See start.ps1 for details.
echo KubeFinOps - local development launcher

set PATH=C:\Program Files\nodejs;%AppData%\npm;%PATH%

for /f "tokens=5" %%a in ('netstat -aon ^| findstr "LISTENING" ^| findstr ":8000 :5173"') do taskkill /F /PID %%a >nul 2>&1

start "KubeFinOps API" cmd /k "cd /d %~dp0backend && python -m pip install -q -r requirements.txt && python run_backend.py"
start "KubeFinOps UI" cmd /k "cd /d %~dp0frontend && (if not exist node_modules npm ci) && npm run dev"

echo.
echo UI:       http://localhost:5173
echo API docs: http://127.0.0.1:8000/docs
echo Sign in as admin@kubefinops.localhost - the password is in backend\.env (created on first run).
echo.
pause
