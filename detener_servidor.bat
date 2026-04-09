@echo off
echo Deteniendo el servidor de Analisis de Resoluciones en segundo plano...
wmic process where "commandline like '%%python%%' and commandline like '%%app.py%%'" call terminate
echo Servidor detenido.
pause
