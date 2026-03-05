#!/bin/bash
# AI PRO TRADING SYSTEM v3.572 - Linux/Mac 启动脚本

echo "============================================================================"
echo "AI PRO TRADING SYSTEM v3.572 - 启动"
echo "============================================================================"

# 检查.env
if [ ! -f ".env" ]; then
    echo "[错误] .env 文件不存在!"
    echo "请先运行 ./setup.sh 并配置 .env"
    exit 1
fi

# 加载环境变量
echo "加载环境变量..."
set -a
source .env
set +a

# 检查关键变量
if [ -z "$OPENAI_API_KEY" ]; then
    echo "[错误] OPENAI_API_KEY 未设置"
    exit 1
fi

if [ -z "$THREECOMMAS_WEBHOOK_URL" ]; then
    echo "[警告] THREECOMMAS_WEBHOOK_URL 未设置 - 加密货币交易将不可用"
fi

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "[警告] 虚拟环境不存在，使用系统Python"
fi

echo ""
echo "启动程序..."

# 创建日志目录
mkdir -p logs

# 启动主程序 (后台)
echo "[1/2] 启动主程序 (端口 ${PORT:-6001})..."
nohup python llm_server_v3570.py > logs/main.log 2>&1 &
MAIN_PID=$!
echo "    PID: $MAIN_PID"

# 等待主程序启动
sleep 8

# 启动扫描引擎 (后台)
echo "[2/2] 启动扫描引擎..."
nohup python price_scan_engine_v16.py > logs/scanner.log 2>&1 &
SCANNER_PID=$!
echo "    PID: $SCANNER_PID"

# 保存PID
echo "$MAIN_PID" > .main.pid
echo "$SCANNER_PID" > .scanner.pid

echo ""
echo "============================================================================"
echo "系统已启动!"
echo ""
echo "  主程序 PID: $MAIN_PID (日志: logs/main.log)"
echo "  扫描器 PID: $SCANNER_PID (日志: logs/scanner.log)"
echo ""
echo "查看日志: tail -f logs/main.log"
echo "停止系统: ./stop.sh"
echo "============================================================================"
