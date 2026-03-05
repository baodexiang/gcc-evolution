#!/bin/bash
# AI PRO TRADING SYSTEM v3.572 - Linux/Mac 安装脚本

echo "============================================================================"
echo "AI PRO TRADING SYSTEM v3.572 - Linux/Mac 安装"
echo "============================================================================"

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到Python3! 请安装Python 3.9+"
    exit 1
fi

echo ""
echo "[1/4] 创建虚拟环境..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "    完成"
else
    echo "    已存在"
fi

echo ""
echo "[2/4] 安装依赖..."
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "    完成"

echo ""
echo "[3/4] 配置环境变量..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "    已创建 .env 文件"
    echo ""
    echo "============================================================"
    echo "重要: 请编辑 .env 文件填入你的API密钥!"
    echo "============================================================"
else
    echo "    .env 已存在"
fi

echo ""
echo "[4/4] 创建目录..."
mkdir -p logs/daily logs/hourly models
echo "    完成"

echo ""
echo "============================================================================"
echo "安装完成!"
echo ""
echo "下一步:"
echo "  1. 编辑 .env 文件: nano .env"
echo "  2. 启动系统: ./start.sh"
echo "============================================================================"
