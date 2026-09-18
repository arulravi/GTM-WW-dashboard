' Waits a bit after login before starting the web server, so it doesn't race
' OneDrive's own startup (OneDrive needs time to mount/hydrate this folder;
' launching too early can silently fail to find server.py). Used by the
' Startup-folder shortcut instead of launching pythonw.exe directly.
Option Explicit
Dim sh, folder, pyw
Set sh = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WScript.Sleep 60000 ' 60 seconds
pyw = "C:\Users\sjp\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\pythonw.exe"
If Not CreateObject("Scripting.FileSystemObject").FileExists(pyw) Then pyw = "pythonw.exe"
sh.Run """" & pyw & """ """ & folder & "\server.py"" --no-browser", 0, False
