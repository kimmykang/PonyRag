@echo off
chcp 65001 >nul 2>&1
echo ================================
echo   Smart Customer Service System
echo ================================
:: 激活 conda 环境
call conda activate test

:: 检查是否激活成功
if errorlevel 1 (
    echo 错误：无法激活 conda 环境 'xiaozhi'
    echo 请确认环境名称是否正确，或先运行 conda init
    pause
    exit /b 1
)

echo 当前 Conda 环境: %CONDA_DEFAULT_ENV%
echo 开始转换当前目录下的文件...

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
echo   Server: http://localhost:8000
echo   Docs:   http://localhost:8000/docs
echo ================================
echo.
echo Press Ctrl+C to stop
echo.

python app.py
