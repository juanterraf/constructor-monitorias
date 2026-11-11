@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Constructor de sentencias monitorias
echo Cerrá esta ventana para apagar el servidor.
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start "" http://127.0.0.1:8765"
python servidor.py
pause
