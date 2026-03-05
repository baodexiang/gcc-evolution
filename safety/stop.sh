#!/bin/bash
# AI PRO TRADING SYSTEM - 停止脚本

echo "停止 AI Trading System..."

if [ -f ".main.pid" ]; then
    MAIN_PID=$(cat .main.pid)
    if kill -0 $MAIN_PID 2>/dev/null; then
        kill $MAIN_PID
        echo "主程序已停止 (PID: $MAIN_PID)"
    fi
    rm .main.pid
fi

if [ -f ".scanner.pid" ]; then
    SCANNER_PID=$(cat .scanner.pid)
    if kill -0 $SCANNER_PID 2>/dev/null; then
        kill $SCANNER_PID
        echo "扫描引擎已停止 (PID: $SCANNER_PID)"
    fi
    rm .scanner.pid
fi

echo "完成"
