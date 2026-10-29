@echo off
rem Daily flood monitor (Windows Task Scheduler entry point).
cd /d "%~dp0.."
if not exist artifacts\monitor mkdir artifacts\monitor
echo ==== %DATE% %TIME% ==== >> artifacts\monitor\scheduler.log
".venv\Scripts\python.exe" -W ignore scripts\monitor_flood.py >> artifacts\monitor\scheduler.log 2>&1
echo exit code %ERRORLEVEL% >> artifacts\monitor\scheduler.log
