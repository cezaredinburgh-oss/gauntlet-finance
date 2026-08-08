@echo off
REM Gauntlet Finance launcher - double-click to start.
REM This window closes immediately; servers run with no console; browser opens.
setlocal EnableExtensions
cd /d "%~dp0"

echo [%DATE% %TIME%] Start-App.bat invoked > "%~dp0launcher.bat.log"
echo Project=%CD%>> "%~dp0launcher.bat.log"

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo ERROR: powershell.exe not found.>> "%~dp0launcher.bat.log"
  msg * "Gauntlet Finance: powershell.exe not found."
  exit /b 1
)

if not exist "%~dp0Start-App.ps1" (
  echo ERROR: Start-App.ps1 missing.>> "%~dp0launcher.bat.log"
  msg * "Gauntlet Finance: Start-App.ps1 missing."
  exit /b 1
)

REM Detached process (NOT start /b - that dies when this console closes).
REM /min + -WindowStyle Hidden = no visible launcher window.
start "GauntletFinance" powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0Start-App.ps1"

echo [%DATE% %TIME%] Launched Start-App.ps1>> "%~dp0launcher.bat.log"
exit /b 0
