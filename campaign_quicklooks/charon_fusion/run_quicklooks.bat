@echo off
REM Launch the CHARON-FUSION quicklooks GUI with the correct venv interpreter.
REM Double-click this file, or run it from a terminal in this folder.
set "VENV=C:\Users\g.gkatzelis\Desktop\My Folders\My Coding\Python\.venv\Scripts"
cd /d "%~dp0"
REM Kill any previous quicklooks instances so we don't pile up on different ports
REM (each old server keeps holding its port, leaving the browser on a stale one).
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'quicklooks_gui' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
"%VENV%\streamlit.exe" run quicklooks_gui.py
pause
