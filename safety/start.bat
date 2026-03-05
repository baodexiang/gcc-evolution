@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================================
echo AI PRO TRADING SYSTEM v3.572 - 启动
echo ============================================================================

:: 检查.env
if not exist ".env" (
    echo [错误] .env 文件不存在!
    echo 请先运行 setup.bat 并配置 .env
    pause
    exit /b 1
)

:: 加载环境变量
echo 加载环境变量...
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "line=%%a"
    set "firstchar=!line:~0,1!"
    if not "!firstchar!"=="#" if not "%%a"=="" (
        set "%%a=%%b"
    )
)

:: 检查关键变量
if "%OPENAI_API_KEY%"=="" (
    echo [错误] OPENAI_API_KEY 未设置
    pause
    exit /b 1
)
if "%THREECOMMAS_WEBHOOK_URL%"=="" (
    echo [警告] THREECOMMAS_WEBHOOK_URL 未设置 - 加密货币交易将不可用
)

:: 激活虚拟环境
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [警告] 虚拟环境不存在，使用系统Python
)

echo.
echo 启动程序...
echo.

:: 启动主程序
echo [1/2] 启动主程序 (端口 %PORT%)...
start "AI-Trading-Main" cmd /k "python llm_server_v3570.py"

:: 等待主程序启动
timeout /t 8 /nobreak >nul

:: 启动扫描引擎
echo [2/2] 启动扫描引擎...
start "AI-Trading-Scanner" cmd /k "python price_scan_engine_v16.py"

echo.
echo ============================================================================
echo 系统已启动!
echo   - 主程序: AI-Trading-Main 窗口
echo   - 扫描器: AI-Trading-Scanner 窗口
echo.
echo 关闭方法: 关闭两个命令窗口
echo ============================================================================
timeout /t 3 >nul
