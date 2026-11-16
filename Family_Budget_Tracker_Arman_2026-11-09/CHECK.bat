@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   Family Budget Tracker - self check before the lesson
echo ============================================================
echo.

python -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    pause
    exit /b 1
)

echo [1/2] Unit tests: 33 checks
echo ------------------------------------------------------------
python -m unittest discover -s tests -v
echo.

echo [2/2] End-to-end check of the data path
echo ------------------------------------------------------------
python selfcheck.py
echo.

echo If both blocks say OK / passed, the application is ready to show.
pause
