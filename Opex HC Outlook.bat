@echo off
REM Launch the native app window (no console). Uses pythonw so nothing lingers.
cd /d "%~dp0"
start "" pythonw "%~dp0app_native.py"
