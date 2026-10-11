@echo off
rem Windows launcher. Everything lives in run.py; this only finds Python and hands over.
cd /d "%~dp0"

set "PY="
where py >nul 2>nul
if %errorlevel%==0 set "PY=py"
if not defined PY (
    where python >nul 2>nul
    if %errorlevel%==0 set "PY=python"
)
if not defined PY (
    echo Python is not installed, or not on PATH.
    echo Install it from https://www.python.org/downloads/windows/
    echo and tick "Add python.exe to PATH" in the installer.
    pause
    exit /b 2
)

%PY% run.py %*
set RC=%errorlevel%
if "%~1"=="" pause
exit /b %RC%
