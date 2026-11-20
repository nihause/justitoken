@echo off
chcp 65001 >nul
title Instalador - USB pela Rede (USB/IP)
setlocal
REM Tudo e relativo a esta pasta: pode ficar em qualquer lugar (C:\usb, USB, etc.)
set "RAIZ=%~dp0"
set "FONTES=%RAIZ%Fontes"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"

:menu
cls
echo ============================================================
echo        USB PELA REDE  -  INSTALADOR (qualquer USB)
echo ============================================================
echo.
echo   Pasta: %RAIZ%
echo   (Linux? use ./instalar.sh)
echo.
echo   --- Passo 1: bibliotecas (1x por PC) ---
echo   [1] Instalar bibliotecas Python (interface)
echo.
echo   --- Passo 2: motor USB/IP ---
echo   [2] PC SERVIDOR: instalar usbipd-win (compartilha USB)
echo   [3] PC ESTACAO:  baixar cliente usbip-win2 (anexa USB)
echo.
echo   --- Passo 3: iniciar com o Windows ---
echo   [4] Este PC sera SERVIDOR (inicia junto com o Windows)
echo   [5] Este PC sera ESTACAO  (inicia junto com o Windows)
echo   [6] Remover inicializacao automatica deste PC
echo.
echo   --- Testar / extras ---
echo   [7] Abrir SERVIDOR agora
echo   [8] Abrir ESTACAO agora
echo   [9] Modo ARQUIVOS sem driver (WebDAV) - so pendrive/HD
echo   [U] Atualizar o programa (GitHub)
echo   [0] Sair
echo.
set /p op="Escolha uma opcao: "

if "%op%"=="1" goto deps
if "%op%"=="2" goto motorsrv
if "%op%"=="3" goto motorcli
if "%op%"=="4" goto srv
if "%op%"=="5" goto est
if "%op%"=="6" goto remover
if "%op%"=="7" goto testsrv
if "%op%"=="8" goto testest
if "%op%"=="9" goto arquivos
if /I "%op%"=="U" goto atualizar
if "%op%"=="0" goto fim
goto menu

:deps
echo.
echo Instalando bibliotecas (customtkinter, wsgidav, cheroot, pystray, pillow)...
py -m pip install --upgrade pip
py -m pip install -r "%FONTES%\requirements.txt"
echo.
pause
goto menu

:motorsrv
echo.
echo Instalando usbipd-win (vai pedir permissao de administrador)...
winget install --id dorssel.usbipd-win -e --source winget --accept-package-agreements --accept-source-agreements
echo.
echo Se instalou, reabra o programa SERVIDOR.
pause
goto menu

:motorcli
echo.
echo Abrindo a pagina de download do cliente usbip-win2...
start "" "https://github.com/vadimgrn/usbip-win2/releases/latest"
echo.
echo Baixe o instalador (.exe), execute e siga os passos.
echo Pode ser necessario reiniciar o PC uma vez.
pause
goto menu

:srv
call :atalho "usb-servidor"
echo.
echo Pronto! Este PC inicia o SERVIDOR junto com o Windows.
pause
goto menu

:est
call :atalho "usb-estacao"
echo.
echo Pronto! Este PC inicia a ESTACAO junto com o Windows.
pause
goto menu

:remover
del /Q "%STARTUP%\usb-servidor.lnk" 2>nul
del /Q "%STARTUP%\usb-estacao.lnk" 2>nul
del /Q "%STARTUP%\usb-servidor.exe" 2>nul
del /Q "%STARTUP%\usb-estacao.exe" 2>nul
del /Q "%STARTUP%\usb-servidor.vbs" 2>nul
del /Q "%STARTUP%\usb-estacao.vbs" 2>nul
echo.
echo Inicializacao automatica removida.
pause
goto menu

:testsrv
start "" "%RAIZ%usb-servidor.vbs"
goto menu

:testest
start "" "%RAIZ%usb-estacao.vbs"
goto menu

:atualizar
echo.
py "%FONTES%\atualizador.py" --verificar
echo.
set /p r="Aplicar a atualizacao agora? (S/N): "
if /I "%r%"=="S" py "%FONTES%\atualizador.py" --aplicar
pause
goto menu

:arquivos
cls
echo --- MODO ARQUIVOS (WebDAV, sem driver) ---
echo Compartilha SO pendrive/HD como uma letra de unidade.
echo   [A] Abrir SERVIDOR (arquivos)
echo   [B] Abrir ESTACAO  (arquivos)
echo   [V] Voltar
set /p o2="Escolha: "
if /I "%o2%"=="A" start "" cmd /c "cd /d "%FONTES%" && py usb_servidor_arquivos.py"
if /I "%o2%"=="B" start "" cmd /c "cd /d "%FONTES%" && py usb_estacao_arquivos.py"
goto menu

REM Cria atalho na pasta Inicializar apontando para o .vbs (silencioso) desta pasta
:atalho
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%STARTUP%\%~1.lnk'); $s.TargetPath='%RAIZ%%~1.vbs'; $s.WorkingDirectory='%RAIZ%'; $s.Save()"
exit /b

:fim
endlocal
