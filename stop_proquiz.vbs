
Option Explicit

Dim shell, xhr

' Create HTTP request object
Set xhr = CreateObject("MSXML2.XMLHTTP")

' Try to shutdown server gracefully first
On Error Resume Next
xhr.Open "POST", "http://127.0.0.1:5000/shutdown", False
xhr.Send

' Force kill any remaining Python processes running app.py
Set shell = CreateObject("WScript.Shell")
shell.Run "taskkill /F /FI ""WINDOWTITLE eq app.py"" /IM pythonw.exe", 0, True