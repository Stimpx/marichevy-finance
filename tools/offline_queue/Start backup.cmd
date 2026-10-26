@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "NODE_OPTIONS="
set "NODE_PATH="
if not exist "%~dp0runtime\node.exe" (
  echo Extract the complete ZIP into a new folder first.
  pause
  exit /b 1
)
"%~dp0runtime\node.exe" --no-global-search-paths --max-old-space-size=256 "%~dp0app\bootstrap.cjs"
pause
