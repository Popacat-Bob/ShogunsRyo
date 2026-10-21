@echo off
title OCR speed test

:: Needs administrator rights, like run.bat (the OCR models were downloaded as administrator).
:: Usage:  ocr_speed.bat        (waits 15 s so you can click on Roblox, like the real app)
::         ocr_speed.bat now    (no wait: measures with this window in front)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    if "%~1"=="" (
        powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1' -Verb RunAs"
    )
    exit /b
)

cd /d "%~dp0"
if /i "%~1"=="now" set OCR_SPEED_DELAY=0
uv run python tools\ocr_speed.py
echo.
pause
