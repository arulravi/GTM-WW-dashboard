' Launch the Opex & HC Outlook dashboard as a chromeless "app" window
' (Edge/Chrome app mode) -- its own window, no tabs or address bar.
' Works offline from disk; falls back to the default browser.
Option Explicit
Dim fso, sh, folder, html, url, browser, paths, i
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

folder = fso.GetParentFolderName(WScript.ScriptFullName)
html   = folder & "\dashboard.html"

If Not fso.FileExists(html) Then
    MsgBox "dashboard.html was not found next to this launcher." & vbCrLf & _
           "Run 'Refresh & Open Dashboard.bat' first.", 48, "Opex & HC Outlook"
    WScript.Quit 1
End If

url = "file:///" & Replace(html, "\", "/")
url = Replace(url, " ", "%20")

paths = Array( _
    sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles%\Google\Chrome\Application\chrome.exe"), _
    sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), _
    sh.ExpandEnvironmentStrings("%LocalAppData%\Google\Chrome\Application\chrome.exe") )

browser = ""
For i = 0 To UBound(paths)
    If browser = "" And fso.FileExists(paths(i)) Then browser = paths(i)
Next

If browser = "" Then
    sh.Run """" & html & """", 1, False
Else
    sh.Run """" & browser & """ --app=""" & url & """ --window-size=1480,940", 1, False
End If
