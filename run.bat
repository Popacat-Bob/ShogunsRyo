@echo off
title ShogunsRyo

:: Re-launch as administrator if not already (needed so Roblox accepts clicks)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: Run from the folder this file is in
cd /d "%~dp0"

where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] uv is not installed or not on PATH.
    echo Install it with:  winget install --id=astral-sh.uv -e
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo [ERROR] No .env file found in this folder.
    echo Copy .env.example to .env and put your GEMINI_API_KEY and GROQ_API_KEY in it.
    echo.
    pause
    exit /b 1
)

:: Mouse speed: fast = about 3x quicker. Change to safe if clicks or scrolls start missing.
set MOUSE_SPEED=fast
:: OCR device: auto = GPU if it works, otherwise CPU. Use cpu to force the CPU.
set OCR_DEVICE=auto
:: Speed: 1 = read a letter's fields in one batch instead of 27 separate trips to the GPU.
:: On the test letter it read text and faint digits better than the original way, and took 0.5 s instead of 1.6 s.
:: 0 = exactly like the original.
set OCR_FAST=1
:: Boost: stops Windows slowing this program down while the game is in front. 0 = off.
set BOOST=1

echo.
echo Starting... (first run installs packages and can take a few minutes)
echo Put Roblox in fullscreen, then press P to start/stop. Ctrl+C here to quit.
echo.

uv run --env-file .env python -m shogunsryo.main

echo.
echo Stopped.
pause
