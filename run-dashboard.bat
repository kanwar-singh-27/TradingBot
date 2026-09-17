@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-dashboard.ps1"
exit /b %errorlevel%