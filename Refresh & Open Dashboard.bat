@echo off
REM One-click: pull the latest numbers from SQL, then open the app window.
cd /d "%~dp0"
echo ============================================================
echo   Opex ^& HC Outlook  --  refreshing data from finance SQL
echo ============================================================
python refresh.py
if errorlevel 1 (
  echo.
  echo Refresh failed - opening the dashboard with existing data.
)
echo.
echo Opening dashboard app...
start "" "Open Dashboard (App).vbs"
