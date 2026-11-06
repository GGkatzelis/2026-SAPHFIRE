@echo off
rem PTR vs injections: opens the desktop window (PyQt), no browser and no console window.
rem Every run is a new, independent window and returns immediately.
rem Uses the shared venv's pythonw.exe (three folders up: ...\Python\.venv) when present.
setlocal
set "HERE=%~dp0"
set "PYW=%HERE%..\..\..\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=%HERE%..\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
start "" "%PYW%" "%HERE%ptr_vs_injections_gui.py" %*
endlocal
