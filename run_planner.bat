@echo off
REM Launch the SAPHFIRE Injection Planner with the correct venv interpreter.
REM Double-click this file, or run it from a terminal in this folder.
set "VENV=C:\Users\g.gkatzelis\Desktop\My Folders\My Coding\Python\.venv\Scripts"
cd /d "%~dp0"
"%VENV%\streamlit.exe" run injection_gui.py
pause
