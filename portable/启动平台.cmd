@echo off
chcp 65001 >nul
cd /d "%~dp0"
"GeoModelingPlatform.exe" start
if errorlevel 1 pause
