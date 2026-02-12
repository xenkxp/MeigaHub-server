@echo off
title MeigaHub Server - Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_server.ps1" -Action stop
echo.
echo === VRAM despues de detener ===
nvidia-smi --query-gpu=name,memory.total,memory.free,memory.used --format=csv,noheader 2>nul || echo nvidia-smi no disponible
echo.
pause
