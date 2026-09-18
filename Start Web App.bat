@echo off
REM Start the Opex & HC Outlook web app and open it in your browser.
REM The link is:  http://localhost:8770/   (bookmark it!)
REM Leave the small server window running while you use the app; close it to stop.
cd /d "%~dp0"
title Opex ^& HC Web Server  --  close this window to stop
start /min "" cmd /c "title Opex ^& HC Web Server (close to stop) && python "%~dp0server.py""
exit
