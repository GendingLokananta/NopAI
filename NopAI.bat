
@echo off
cd /d "%~dp0"

set "PYTHONW="

where pyw >nul 2>&1
if not errorlevel 1 (
    start "" pyw "%~dp0main.py"
    exit
)

for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)"') do set "PYTHON=%%P"
set "PYTHONW=%PYTHON:python.exe=pythonw.exe%"

if exist "%PYTHONW%" (
    start "" "%PYTHONW%" "%~dp0main.py"
) else (
    start "" pythonw "%~dp0main.py"
)

exit
