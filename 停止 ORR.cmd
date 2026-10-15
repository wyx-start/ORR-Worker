@echo off
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0launch.py" --stop
) else (
    start "" pyw -3.13 "%~dp0launch.py" --stop
)
