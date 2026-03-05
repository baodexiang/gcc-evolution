@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================================
echo AI PRO TRADING SYSTEM v3.572 - 一键启动
echo ============================================================================

:: 检查.env
if not exist ".env" (
    echo [错误] 请先配置 .env 文件
    pause
    exit /b 1
)

:: 加载环境变量
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "firstchar=%%a"
    set "firstchar=!firstchar:~0,1!"
    if not "!firstchar!"=="#" if not "%%a"=="" set "%%a=%%b"
)

:: 激活虚拟环境
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo.
echo [1/2] 启动主程序 (端口 %PORT%)...
start "AI-Trading-Main" cmd /k "python llm_server_v3570.py"

timeout /t 5 /nobreak >nul

echo [2/2] 启动扫描引擎...
start "AI-Trading-Scanner" cmd /k "python price_scan_engine_v16.py"

echo.
echo ============================================================================
echo 系统已启动！
echo   - 主程序窗口: AI-Trading-Main
echo   - 扫描引擎窗口: AI-Trading-Scanner
echo ============================================================================
