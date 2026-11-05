@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Check if already running on port 8799
netstat -ano | findstr ":8799" | findstr "LISTENING" >nul
if not errorlevel 1 (
  echo Workbench already running. Opening browser...
  start "" http://127.0.0.1:8799
  exit /b 0
)

echo Starting DSH Workbench at http://127.0.0.1:8799 ...
start "" http://127.0.0.1:8799
python server.py --port 8799