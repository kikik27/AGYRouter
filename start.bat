@echo off
title AGY Local API Proxy
echo ========================================================
echo   Starting AGY Official Local API Proxy Server
echo ========================================================

IF EXIST .venv\Scripts\python.exe (
    .venv\Scripts\python.exe run.py
) ELSE (
    python run.py
)
pause
