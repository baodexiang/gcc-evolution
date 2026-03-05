@echo off
chcp 65001 >nul
echo ============================================================================
echo AI PRO TRADING SYSTEM v3.572 - Windows 安装
echo ============================================================================

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python! 请安装Python 3.9+
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo [1/4] 创建虚拟环境...
if not exist ".venv" (
    python -m venv .venv
    echo     完成
) else (
    echo     已存在
)

echo.
echo [2/4] 安装依赖...
call .venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo     完成

echo.
echo [3/4] 配置环境变量...
if not exist ".env" (
    copy .env.example .env >nul
    echo     已创建 .env 文件
    echo.
    echo ============================================================
    echo 重要: 请编辑 .env 文件填入你的API密钥!
    echo ============================================================
) else (
    echo     .env 已存在
)

echo.
echo [4/4] 创建目录...
if not exist "logs" mkdir logs
if not exist "logs\daily" mkdir logs\daily
if not exist "models" mkdir models
echo     完成

echo.
echo ============================================================================
echo 安装完成!
echo.
echo 下一步:
echo   1. 编辑 .env 文件填入API密钥
echo   2. 运行 start.bat 启动系统
echo ============================================================================
pause
