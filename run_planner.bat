@echo off
REM Launch the SAPHFIRE Injection Planner with the correct venv interpreter.
REM Double-click this file, or run it from a terminal in this folder.
set "VENV=C:\Users\g.gkatzelis\Desktop\My Folders\My Coding\Python\.venv\Scripts"
cd /d "%~dp0"
REM Kill any previous planner instances so we don't pile up on different ports
REM (each old server keeps holding its port, leaving the browser on a stale one).
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'injection_gui' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
"%VENV%\streamlit.exe" run injection_gui.py
pause
