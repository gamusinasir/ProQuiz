Option Explicit

Dim shell, fso, pythonCmd, currentDir, waitTime

' Get current directory
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = "D:\ProQuiz"

' Create shell object
Set shell = CreateObject("WScript.Shell")

' Change to project directory
shell.CurrentDirectory = currentDir

' Activate virtual environment and run Flask app (hidden)
pythonCmd = currentDir & "\venv\Scripts\pythonw.exe " & currentDir & "\app.py"
shell.Run pythonCmd, 0, False

' Wait 2 seconds for server to start
waitTime = 2
WScript.Sleep waitTime * 1000

' Open browser
shell.Run "http://127.0.0.1:5000"
