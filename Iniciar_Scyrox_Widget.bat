@echo off
setlocal
cd /d "%~dp0"

if exist "dist\ScyroxWidget\ScyroxWidget.exe" (
    cd /d "%~dp0dist\ScyroxWidget"
    start "" "ScyroxWidget.exe"
    exit
)

start "" pythonw main.py
exit
