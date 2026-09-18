@echo off
REM One-click launcher for the Opex & HC Outlook dashboard.
REM Opens the dashboard in your default browser.
cd /d "%~dp0"
echo Starting Opex ^& HC Outlook dashboard...
python -m streamlit run app.py --server.port 8501
pause
