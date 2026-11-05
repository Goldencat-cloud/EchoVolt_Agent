@echo off
setlocal
rem Avoid inherited PowerShell 7 modules shadowing Windows PowerShell modules.
set "PSModulePath="
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy.ps1" %*
if errorlevel 1 (
  echo Deployment failed. See the error above.
  pause
  exit /b 1
)
endlocal
