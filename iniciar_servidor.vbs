Set WshShell = CreateObject("WScript.Shell")
' El 0 al final indica que la ventana cmd correrá completamente oculta
WshShell.Run "cmd /c cd /d ""e:\sistema RD"" && python app.py", 0, False
