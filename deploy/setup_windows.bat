@echo off
chcp 65001 >nul
echo ============================================================================
echo AI PRO TRADING SYSTEM v3.572 - Windows 部署脚本
echo ============================================================================

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.9+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo [步骤1] 创建虚拟环境...
if not exist ".venv" (
    python -m venv .venv
    echo 虚拟环境创建成功
) else (
    echo 虚拟环境已存在，跳过创建
)

echo.
echo [步骤2] 激活虚拟环境并安装依赖...
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r deploy\requirements.txt

echo.
echo [步骤3] 检查.env文件...
if not exist ".env" (
    echo [警告] .env文件不存在
    echo 正在从模板创建...
    copy deploy\.env.example .env
    echo.
    echo ============================================================================
    echo 重要: 请编辑 .env 文件，填入你的API密钥:
    echo   - OPENAI_API_KEY
    echo   - DEEPSEEK_API_KEY
    echo   - THREECOMMAS_WEBHOOK_URL
    echo   - THREECOMMAS_SECRET
    echo ============================================================================
) else (
    echo .env文件已存在
)

echo.
echo [步骤4] 创建必要目录...
if not exist "logs" mkdir logs
if not exist "logs\daily" mkdir logs\daily
if not exist "logs\hourly" mkdir logs\hourly
if not exist "logs\decisions" mkdir logs\decisions
if not exist "logs\deepseeklogs" mkdir logs\deepseeklogs

echo.
echo ============================================================================
echo 部署完成！
echo.
echo 启动方法:
echo   1. 设置环境变量: 编辑 .env 文件后运行 load_env.bat
echo   2. 启动主程序:   python llm_server_v3570.py
echo   3. 启动扫描引擎: python price_scan_engine_v16.py
echo   4. 启动监控:     python monitor_v3570.py (可选)
echo ============================================================================
pause
