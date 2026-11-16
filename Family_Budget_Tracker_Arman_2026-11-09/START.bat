@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   Family Budget Tracker - Team 38
echo   Akhmetshiev Arman, 24B030051
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    echo Install Python 3.12 from https://www.python.org/downloads/
    echo During installation tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version') do set "PYVER=%%v"
echo Python found: %PYVER%
echo.

python -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo First start: installing dependencies.
    echo This takes 2-5 minutes and needs internet. Please wait...
    echo.
    python -m pip install --upgrade pip >nul 2>nul
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Installation failed.
        echo The usual reason on Python 3.14 is a package without a ready build yet.
        echo Fix: install Python 3.12 from python.org and run this file again.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo Dependencies installed.
    echo.
)

if not exist "data\family_budget.db" (
    echo Creating the demo family with six months of transactions...
    python seed_demo.py
    echo.
)

if exist "postgres_url.txt" (
    set /p DATABASE_URL=<postgres_url.txt
    echo Using PostgreSQL from postgres_url.txt
    echo.
)

echo Starting the application at http://localhost:8501
echo The browser opens automatically.
echo Keep this window open while you show the project. Press Ctrl+C to stop.
echo.
python -m streamlit run app.py

echo.
echo The application has stopped.
pause
