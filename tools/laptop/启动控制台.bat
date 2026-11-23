@echo off
chcp 65001 >nul
cd /d "%~dp0"
title bobac practicum console

set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"

if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo [ERROR] Python 3 not found.
    echo Install from https://www.python.org/downloads/ and tick "Add Python to PATH".
    pause
    exit /b 1
)

%PY% -c "import paramiko" >nul 2>&1
if errorlevel 1 (
    echo [INFO] installing paramiko ...
       if errorlevel 1 (
        echo [ERROR] pip install failed, run manually: pip install paramiko
        pause
        exit /b 1
    )
)

%PY% bobac_console.py
if errorlevel 1 pause
