' Creates a Desktop (and Start-menu) shortcut for the GTM WW Opex & HC Outlook app,
' with the custom icon. Double-click once; then launch the app from the icon.
Option Explicit
Dim fso, sh, folder, target, icon, lnk, sc, startDir, msg

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

folder = fso.GetParentFolderName(WScript.ScriptFullName)
icon   = folder & "\app.ico"

' Prefer pythonw.exe (no console) for a clean native app window.
Dim pyw
pyw = ""
Dim cand
For Each cand In Array( _
    sh.ExpandEnvironmentStrings("%LocalAppData%\Programs\Python\Python314\pythonw.exe"), _
    sh.ExpandEnvironmentStrings("%LocalAppData%\Programs\Python\Python313\pythonw.exe"), _
    sh.ExpandEnvironmentStrings("%LocalAppData%\Programs\Python\Python312\pythonw.exe") )
    If pyw = "" And fso.FileExists(cand) Then pyw = cand
Next
If pyw = "" Then pyw = "pythonw.exe"   ' fall back to PATH

Function MakeShortcut(path)
    Dim s
    Set s = sh.CreateShortcut(path)
    s.TargetPath       = pyw
    s.Arguments        = """app_native.py"""
    s.WorkingDirectory = folder
    s.WindowStyle      = 1
    s.Description       = "GTM WW Opex & HC Outlook — FY26 executive dashboard"
    If fso.FileExists(icon) Then s.IconLocation = icon & ", 0"
    s.Save
End Function

' Desktop
lnk = sh.SpecialFolders("Desktop") & "\GTM WW Opex & HC Outlook.lnk"
MakeShortcut(lnk)

' Start Menu > Programs
On Error Resume Next
startDir = sh.SpecialFolders("Programs")
If fso.FolderExists(startDir) Then MakeShortcut(startDir & "\GTM WW Opex & HC Outlook.lnk")
On Error Goto 0

msg = "Created a shortcut on your Desktop" & vbCrLf & _
      "(and in the Start menu):" & vbCrLf & vbCrLf & _
      "   GTM WW Opex & HC Outlook" & vbCrLf & vbCrLf & _
      "Double-click it to launch the app. Use the 🔄 Refresh button" & vbCrLf & _
      "inside the app to pull the latest numbers from SQL."
MsgBox msg, 64, "GTM WW Opex & HC Outlook"
