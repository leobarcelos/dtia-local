@echo off
setlocal
set "DTIA_DATA=%LOCALAPPDATA%\DTIA Local"
if not exist "%DTIA_DATA%" mkdir "%DTIA_DATA%"
start "" "%DTIA_DATA%"

