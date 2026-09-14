@echo off
title ED LawBase
cd /d "%~dp0\.."
if exist "python\python.exe" (
  "python\python.exe" app\server.py
) else (
  python app\server.py
)
if errorlevel 1 pause
