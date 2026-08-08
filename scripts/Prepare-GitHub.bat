@echo off
REM Bypass PowerShell execution policy for this one script only (does not change system settings).
setlocal
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Prepare-GitHub.ps1" %*
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo FAILED with exit code %ERR%
  pause
  exit /b %ERR%
)
echo.
pause
exit /b 0
