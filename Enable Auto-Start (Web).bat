@echo off
REM Turn ON launch-at-login for the web app (link always live at localhost:8770),
REM and start it right now.
powershell -NoProfile -Command "$f='%~dp0'.TrimEnd('\'); $ws=New-Object -ComObject WScript.Shell; $pyw=(Get-Command pythonw -ErrorAction SilentlyContinue).Source; if(-not $pyw){ $pyw='pythonw.exe' }; $sc=Join-Path ([Environment]::GetFolderPath('Startup')) 'GTM WW Web Server.lnk'; $l=$ws.CreateShortcut($sc); $l.TargetPath=$pyw; $l.Arguments='\"'+$f+'\server.py\" --no-browser'; $l.WorkingDirectory=$f; $l.WindowStyle=7; if(Test-Path (Join-Path $f 'app.ico')){ $l.IconLocation=(Join-Path $f 'app.ico')+',0' }; $l.Save(); if(-not (Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue)){ Start-Process -FilePath $pyw -ArgumentList ('\"'+$f+'\server.py\"','--no-browser') -WorkingDirectory $f }; 'Auto-start ENABLED. Link is live at http://localhost:8770/'"
pause
