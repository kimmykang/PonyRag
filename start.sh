#!/bin/bash
set -e

echo "================================"
echo "  智能客服系统 - 启动脚本"
echo "================================"
echo ""

# 进入 backend 目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3，请先安装 Python 3.10+"
    exit 1
fi

echo "[1/4] 进入 backend 目录..."

echo "[2/4] 安装依赖..."
pip install -r requirements.txt -q

echo "[3/4] 检查 Ollama 是否运行..."
if ! curl -s http://localhost:11434/api/tags &> /dev/null; then
    echo "[警告] 无法连接到 Ollama (localhost:11434)"
    echo "       请先启动 Ollama: https://ollama.ai"
    exit 1
fi
echo "Ollama 连接正常!"

echo "[4/4] 启动服务..."
echo ""
echo "================================"
echo "  服务地址: http://localhost:8000"
echo "  API文档:  http://localhost:8000/docs"
echo "================================"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

python app.py
