@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   Public link for Family Budget Tracker
echo ============================================================
echo.
echo The app must already be running: START.bat in another window.
echo.

if not exist "tools\cloudflared.exe" (
    echo First run: downloading the tunnel client ~55 MB. Please wait...
    if not exist "tools" mkdir "tools"
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'tools\cloudflared.exe'"
    if not exist "tools\cloudflared.exe" (
        echo [ERROR] Download failed. Check the internet connection.
        pause
        exit /b 1
    )
)

echo.
echo Starting the tunnel to http://localhost:8501
echo Look for the line:  https://....trycloudflare.com
echo Keep this window open while somebody uses the link.
echo Press Ctrl+C to stop the tunnel.
echo.

"tools\cloudflared.exe" tunnel --url http://localhost:8501 --no-autoupdate

echo.
echo Tunnel stopped. The public link no longer works.
pause
