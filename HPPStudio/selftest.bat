@echo off
REM Uji engine tanpa GUI (butuh numpy, pandas, openpyxl, matplotlib)
setlocal
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\hppstudio-venv"
if exist "%VENV%\Scripts\python.exe" (
    "%VENV%\Scripts\python.exe" selftest.py
) else (
    python selftest.py
)
pause
