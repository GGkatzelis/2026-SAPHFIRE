@echo off
rem Evaluate everything in Incoming - Upload now and open the report (no email).
cd /d "%~dp0"
"C:\Users\g.gkatzelis\Desktop\My Folders\My Coding\Python\.venv\Scripts\python.exe" evaluate.py --open %*
pause
