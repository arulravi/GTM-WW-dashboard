@echo off
REM Turn OFF launch-at-login for the web app, and stop it if it's running now.
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\GTM WW Web Server.lnk" 2>nul
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue; if($c){ $c | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } ; 'Stopped the running web server.' } else { 'Web server was not running.' }"
echo Auto-start DISABLED. The web link will no longer start at login.
echo (Re-enable anytime with 'Enable Auto-Start (Web).bat'.)
pause
