@echo off
REM Abre o SERVIDOR com janela (util para testar / ver erros).
cd /d "%~dp0Fontes"
py usb_servidor.py
pause
