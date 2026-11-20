@echo off
REM Verifica e aplica a atualizacao do programa a partir do GitHub.
cd /d "%~dp0Fontes"
py atualizador.py --verificar
if errorlevel 10 goto pergunta
goto fim

:pergunta
set /p r="Ha atualizacao. Aplicar agora? (S/N): "
if /I "%r%"=="S" py atualizador.py --aplicar

:fim
pause
