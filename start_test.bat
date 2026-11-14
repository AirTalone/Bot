@echo off
title Exchange bot - TEST
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install it from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
)
python scripts\start_test.py
pause
