@echo off
chcp 65001 >nul 2>&1
echo ================================
echo   Smart Customer Service System
echo ================================

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

echo [1/4] Changing to backend directory...
cd /d "%~dp0backend"
if errorlevel 1 (
    echo [ERROR] Cannot change to backend directory
    pause
    exit /b 1
)



echo [4/4] Starting server...
echo.
echo ================================
echo   Server: http://localhost:8001
echo   Docs:   http://localhost:8001/docs
echo ================================
echo.
echo Press Ctrl+C to stop
echo.

python app.py
