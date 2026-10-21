@echo off
title Check models
cd /d "%~dp0"
if not exist ".env" (
    echo [ERROR] No .env file found in this folder.
    pause
    exit /b 1
)
uv run --env-file .env python tools\check_models.py
echo.
pause
