@echo off
REM Abre a ESTACAO com janela (util para testar / ver erros).
cd /d "%~dp0Fontes"
py usb_estacao.py
pause
