@echo off
rem Stops Dash FIDCs (app + PostgreSQL).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1" %*
if errorlevel 1 (
    pause
    exit /b 1
)
timeout /t 5 >nul
