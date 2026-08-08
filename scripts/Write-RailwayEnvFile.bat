@echo off
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Write-RailwayEnvFile.ps1" %*
if errorlevel 1 pause
exit /b %ERRORLEVEL%
