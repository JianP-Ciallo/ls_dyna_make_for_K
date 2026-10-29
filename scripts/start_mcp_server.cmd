@echo off
setlocal
set "ROOT=%~dp0.."
set "PYTHONDONTWRITEBYTECODE=1"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\start_mcp_server.ps1"
exit /b %ERRORLEVEL%
