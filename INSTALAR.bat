@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Instalador — DTIA Local

echo.
echo  DATATECH IMAGE ARCHIVES — LOCAL
echo  Instalação segura no seu computador
echo.

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  where python >nul 2>nul && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  echo O Python 3 ainda não está instalado.
  where winget >nul 2>nul || goto :no_python
  set /p "INSTALL_PYTHON=Deseja instalar o Python 3 pelo Windows agora? [S/N]: "
  if /I not "%INSTALL_PYTHON%"=="S" goto :no_python
  winget install --id Python.Python.3.12 -e --source winget
  if errorlevel 1 goto :failed
  set "PYTHON_CMD=py -3"
)

echo Criando o ambiente privado do DTIA Local...
%PYTHON_CMD% -m venv .venv
if errorlevel 1 goto :failed

echo Instalando o processador de imagens...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :failed

echo.
echo Instalação concluída.
echo Agora use INICIAR.bat para abrir o DTIA Local.
echo.
pause
exit /b 0

:no_python
echo.
echo Instale o Python 3.12 pela Microsoft Store ou em python.org e execute este arquivo novamente.
pause
exit /b 1

:failed
echo.
echo A instalação não foi concluída. Verifique sua conexão e tente novamente.
pause
exit /b 1

