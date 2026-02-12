@echo off
title MeigaHub-server - Instalador
color 0B
echo.
echo   Iniciando instalador de MeigaHub-server...
echo   Los backends se descargaran automaticamente de GitHub.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer.ps1"
