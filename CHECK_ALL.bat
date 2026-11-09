@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   Family Budget Tracker - full check
echo   Team 38 / Akhmetshiev Arman
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not found in PATH.
    pause
    exit /b 1
)

echo [1/3] Unit tests (expect: 34 tests, OK)
echo ------------------------------------------------------------
python -m unittest discover -s tests -v
echo.

echo [2/3] End-to-end data path (expect: 10/10 checks passed)
echo ------------------------------------------------------------
python selfcheck.py
echo.

echo [3/3] Database contract
echo ------------------------------------------------------------
if exist "postgres_url.txt" goto pg
echo No postgres_url.txt - checking the SQLite demo file
python tools\db_check.py --sqlite "data\family_budget.db"
goto after_pg
:pg
set /p DATABASE_URL=<postgres_url.txt
python tools\db_check.py
:after_pg

echo.
echo Done. If all three blocks are OK, the build is ready to show.
echo The 36-case suite belongs to Nurbol and runs from his folder:
echo   set FBT_APP=%CD%
echo   python team_suite.py
echo.
pause
