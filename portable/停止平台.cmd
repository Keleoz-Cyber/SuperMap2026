@echo off
chcp 65001 >nul
cd /d "%~dp0"
"GeoModelingPlatform.exe" stop
if errorlevel 1 pause
