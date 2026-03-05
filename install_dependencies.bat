@echo off
echo Installing dependencies...
python -m pip install --upgrade pip
if exist requirements.txt (
    python -m pip install -r requirements.txt
) else (
    echo requirements.txt not found!
)
echo.
echo Installation complete.
pause
