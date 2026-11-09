@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   Team 38 - checks with the receipt module
echo   (unit tests + data path + receipts)
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    pause
    exit /b 1
)

echo [1/3] Unit tests (expect: 34 tests, OK)
echo ------------------------------------------------------------
python -m unittest discover -s tests
echo.

echo [2/3] End-to-end data path (expect: 10/10)
echo ------------------------------------------------------------
python selfcheck.py
echo.

echo [3/3] Receipt module (expect: PASS attach, list, read, delete)
echo ------------------------------------------------------------
python test_receipts.py
echo.

echo If all three blocks are OK, the build with receipts is ready.
pause
