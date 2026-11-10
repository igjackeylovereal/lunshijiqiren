@echo off
chcp 65001 >nul
cd /d "%~dp0"
title bobac launcher

if exist ".venv\Scripts\python.exe" goto run

echo [INFO] first run: creating .venv ...
py -3 -m venv .venv >nul 2>&1
if errorlevel 1 python -m venv .venv

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] cannot create venv. Run ?????.bat once, or install Python 3.
    pause
    exit /b 1
)

echo [INFO] installing paramiko ...
".venv\Scripts\python.exe" -m pip install --upgrade "pip<25" -i https://pypi.tuna.tsinghua.edu.cn/simple
".venv\Scripts\python.exe" -m pip install paramiko -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)

:run
".venv\Scripts\python.exe" bobac_launcher.py
if errorlevel 1 pause
