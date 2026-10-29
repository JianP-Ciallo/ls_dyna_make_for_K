@echo off
setlocal
set "ROOT=%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\start_web_app.ps1" -OpenBrowser -SkipDoctor %*
if errorlevel 1 (
  echo.
  echo lsprepost-mcp Web App failed to start. Check the error above.
  pause
)
exit /b %ERRORLEVEL%
