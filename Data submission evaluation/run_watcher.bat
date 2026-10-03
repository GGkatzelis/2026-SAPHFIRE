@echo off
rem SAPHFIRE 2026 upload watcher: emails an evaluation report for every new upload.
rem Started at log-in by Task Scheduler; safe to double-click (only one instance runs).
cd /d "%~dp0"
"C:\Users\g.gkatzelis\Desktop\My Folders\My Coding\Python\.venv\Scripts\pythonw.exe" watcher.py
