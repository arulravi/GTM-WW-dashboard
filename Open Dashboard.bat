@echo off
REM Open the dashboard using the data already refreshed (no SQL pull).
cd /d "%~dp0"
start "" "dashboard.html"
