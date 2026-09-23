@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title DTIA Local

if not exist ".venv\Scripts\python.exe" (
  echo O DTIA Local ainda não foi instalado.
  call INSTALAR.bat
  if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" dtia_local.py

