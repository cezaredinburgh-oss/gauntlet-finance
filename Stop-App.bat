@echo off
REM Stop Gauntlet Finance — no leftover console (hidden PowerShell, bat exits immediately).
setlocal
cd /d "%~dp0"
start "" /min powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0Stop-App.ps1"
exit /b 0
