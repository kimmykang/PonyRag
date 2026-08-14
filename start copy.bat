@echo off
chcp 65001 >nul 2>&1
echo ================================
echo   Smart Customer Service System
echo ================================
echo.

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

echo [2/4] Installing dependencies...
pip install -r requirements.txt -q

echo [3/4] Checking Ollama connection...
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [WARN] Cannot connect to Ollama (localhost:11434)
    echo        Please start Ollama first: https://ollama.ai
    echo.
    pause
    exit /b 1
)
echo Ollama is running!

echo [4/4] Starting server...
echo.
echo ================================
echo   Server: http://localhost:8000
echo   Docs:   http://localhost:8000/docs
echo ================================
echo.
echo Press Ctrl+C to stop
echo.

python app.py
