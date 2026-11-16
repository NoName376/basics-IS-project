@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   PostgreSQL setup - option B
echo   our schema + Alibek's records
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    pause
    exit /b 1
)

python -c "import psycopg2" >nul 2>nul
if errorlevel 1 (
    echo Installing the PostgreSQL driver...
    python -m pip install psycopg2-binary
    if errorlevel 1 (
        echo [ERROR] Could not install psycopg2-binary. Check the internet connection.
        pause
        exit /b 1
    )
)

if "%~1"=="" (
    python tools\setup_postgres.py
) else (
    python tools\setup_postgres.py --data "%~1"
)

echo.
pause
