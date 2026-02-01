@echo off
echo Starting Portfolio Dashboard...

:: Navigate to project root
cd /d "%~dp0"

:: Start Backend
echo Starting Backend Server...
cd backend
start "Portfolio Backend" cmd /k "python server.py"
cd ..

:: Start Frontend
echo Starting Frontend Server...
start "Portfolio Frontend" cmd /k "npm run dev"

:: Wait for servers to initialize
echo Waiting for servers to initialize...
timeout /t 10 >nul

:: Open in Chrome
echo Opening Dashboard in Chrome...
start chrome http://localhost:5173

exit
