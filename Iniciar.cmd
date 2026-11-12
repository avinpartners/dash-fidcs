@echo off
rem Starts Dash FIDCs (PostgreSQL + app) and opens the browser.
rem The first run also prepares this computer (scripts\setup.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1" %*
if errorlevel 1 (
    echo.
    echo Algo deu errado. Leia a mensagem acima.
    pause
    exit /b 1
)
echo.
echo Esta janela fecha sozinha em 30 segundos. O Dash FIDCs continua rodando.
timeout /t 30 >nul
