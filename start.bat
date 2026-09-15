@echo off
echo ======================================================================
echo    Kubernetes FinOps & Cost-Optimization Dashboard - One-Click Launcher
echo ======================================================================
echo.

set PATH=C:\Program Files\nodejs;%AppData%\npm;%PATH%

echo Freeing occupied ports 8000 and 5173 if running...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 :5173"') do taskkill /F /PID %%a >nul 2>&1

echo Starting Python FastAPI Backend on http://127.0.0.1:8000 ...
start "K8s FinOps Backend" cmd /k "cd backend && python -m pip install -r requirements.txt && python run_backend.py"

echo Starting React + Vite Frontend on http://localhost:5173 ...
start "K8s FinOps Frontend" cmd /k "set PATH=C:\Program Files\nodejs;%AppData%\npm;%PATH% && cd frontend && npm run dev"

echo.
echo All services launched! 
echo Frontend Dashboard: http://localhost:5173
echo Backend REST Swagger: http://127.0.0.1:8000/docs
echo.
pause
