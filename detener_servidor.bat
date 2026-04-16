@echo off
echo Deteniendo el servidor de Analisis de Resoluciones en segundo plano...
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'python.*app\.py' } | Invoke-CimMethod -MethodName Terminate"
echo Servidor detenido.
pause
