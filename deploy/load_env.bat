@echo off
chcp 65001 >nul
echo 正在从 .env 文件加载环境变量...

:: 检查.env文件是否存在
if not exist ".env" (
    echo [错误] .env 文件不存在
    echo 请先复制 deploy\.env.example 为 .env 并填入配置
    pause
    exit /b 1
)

:: 读取.env文件并设置环境变量
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    :: 跳过注释和空行
    set "line=%%a"
    if not "!line:~0,1!"=="#" (
        if not "%%a"=="" (
            set "%%a=%%b"
            echo   设置 %%a
        )
    )
)

setlocal enabledelayedexpansion
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "line=%%a"
    if not "!line:~0,1!"=="#" if not "%%a"=="" set "%%a=%%b"
)
endlocal & (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        set "firstchar=%%a"
        setlocal enabledelayedexpansion
        set "firstchar=!firstchar:~0,1!"
        if not "!firstchar!"=="#" if not "%%a"=="" (
            endlocal
            set "%%a=%%b"
        ) else (
            endlocal
        )
    )
)

echo.
echo 环境变量加载完成！
echo.
echo 现在可以运行:
echo   python llm_server_v3570.py
echo   python price_scan_engine_v16.py
