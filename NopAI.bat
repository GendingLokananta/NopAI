@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0main.py" (
    echo ERROR: main.py tidak ditemukan.
    echo Simpan file Buka_NopAI.bat di folder yang sama dengan main.py.
    pause
    exit /b 1
)

if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "NopAI" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b 0
)

if exist "%~dp0.venv\Scripts\python.exe" (
    start "NopAI" "%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
    exit /b 0
)

echo ERROR: Python virtual environment .venv tidak ditemukan.
echo Pastikan folder .venv berada di folder yang sama dengan main.py.
pause
exit /b 1
