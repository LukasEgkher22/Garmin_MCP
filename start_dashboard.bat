@echo off
REM Starts the local training dashboard at http://127.0.0.1:8765 (close this window to stop it)
cd /d "%~dp0"
".venv\Scripts\python.exe" dashboard.py
pause
