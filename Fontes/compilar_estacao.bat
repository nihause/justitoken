@echo off
REM ===================================================================
REM  JustiToken - compila SOMENTE a Estacao (dist\usb-estacao.exe)
REM  O Servidor (usb-servidor.exe) NAO e recompilado nem substituido.
REM ===================================================================
cd /d "%~dp0"
chcp 65001 >nul

if exist "dist\usb-estacao.exe" if not exist "dist\usb-estacao_v2.0.0_backup.exe" (
    copy /y "dist\usb-estacao.exe" "dist\usb-estacao_v2.0.0_backup.exe" >nul
    echo Backup do executavel anterior: dist\usb-estacao_v2.0.0_backup.exe
)

py -m pip install -q -r requirements.txt pyinstaller
if errorlevel 1 goto erro

py -m PyInstaller --noconfirm usb-estacao.spec
if errorlevel 1 goto erro

echo.
echo OK - gerado dist\usb-estacao.exe (JustiToken Estacao 3.0.0)
pause
exit /b 0

:erro
echo.
echo FALHA na compilacao. Veja as mensagens acima.
pause
exit /b 1
