@echo off
chcp 65001 >nul 2>&1
echo ================================
echo   PonyRAG Knowledge Base System
echo ================================

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

echo [1/3] Locating backend directory...
set "BACKEND_DIR=%~dp0backend"

if not exist "%BACKEND_DIR%" (
    echo [ERROR] Cannot find backend directory: %BACKEND_DIR%
    pause
    exit /b 1
)

echo [2/3] Changing to backend directory...
cd /d "%BACKEND_DIR%"
if errorlevel 1 (
    echo [ERROR] Cannot change to backend directory
    pause
    exit /b 1
)

echo [3/3] Starting server...
echo.
echo ================================
echo   Server: http://localhost:8001
echo   Docs:   http://localhost:8001/docs
echo ================================
echo.
echo Press Ctrl+C to stop
echo.

python app.py

pause
