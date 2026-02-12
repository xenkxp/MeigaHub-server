@echo off
title MeigaHub Server
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_server.ps1" -Action start
pause
