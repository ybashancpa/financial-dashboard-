@echo off
setlocal EnableDelayedExpansion
title Globes Summarizer - Setup

echo.
echo  ============================================
echo    Globes Daily Summarizer ^| Setup Script
echo  ============================================
echo.

:: ── Check Python ─────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found.
    echo  Download Python 3.10+ from: https://www.python.org/downloads/
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo  Python found: %%i
echo.

:: ── Install dependencies ──────────────────────────────────────────────────────
echo  [1/3] Installing Python packages...
pip install -r "%~dp0requirements.txt" --quiet
if errorlevel 1 (
    echo  [ERROR] pip install failed. Try running as Administrator.
    pause & exit /b 1
)
echo  Packages installed successfully.
echo.

:: ── Check .env ────────────────────────────────────────────────────────────────
echo  [2/3] Checking .env configuration...
if not exist "%~dp0.env" (
    echo  [ERROR] .env file not found in %~dp0
    echo  Please create it based on the README instructions.
    pause & exit /b 1
)

:: Quick check for required vars
findstr /C:"CLAUDE_API_KEY=" "%~dp0.env" >nul
if errorlevel 1 (
    echo  [WARNING] CLAUDE_API_KEY not found in .env – please fill it in.
)
findstr /C:"GMAIL_APP_PASSWORD=" "%~dp0.env" >nul
if errorlevel 1 (
    echo  [WARNING] GMAIL_APP_PASSWORD not found in .env – please fill it in.
)
echo  .env file found.
echo.

:: ── Task Scheduler ────────────────────────────────────────────────────────────
echo  [3/3] Registering Windows Task Scheduler job (daily 07:00)...

:: Resolve paths
set "SCRIPT=%~dp0globes_scraper.py"
for /f "tokens=*" %%i in ('where python') do (
    set "PYEXE=%%i"
    goto :found_python
)
:found_python

:: Build the task command (change directory first so .env is found)
set "TASK_CMD=cmd /c cd /d ^"%~dp0^" ^&^& ^"!PYEXE!^" ^"%SCRIPT%^""

schtasks /create ^
    /tn "GlobesDailySummary" ^
    /tr "%TASK_CMD%" ^
    /sc DAILY ^
    /st 07:00 ^
    /rl HIGHEST ^
    /f >nul 2>&1

if errorlevel 1 (
    echo  [WARNING] Could not create scheduled task.
    echo  Try running this script as Administrator, or add the task manually:
    echo.
    echo    schtasks /create /tn "GlobesDailySummary" /tr "python \"%SCRIPT%\"" /sc DAILY /st 07:00
    echo.
) else (
    echo  Scheduled task "GlobesDailySummary" created – runs daily at 07:00.
)

echo.
echo  ============================================
echo    Setup complete!
echo  ============================================
echo.
echo  Next steps:
echo    1. Edit .env  ^(fill CLAUDE_API_KEY ^& GMAIL_APP_PASSWORD^)
echo    2. Test now:   python "%~dp0globes_scraper.py"
echo    3. The task will run automatically every day at 07:00.
echo.
echo  Manage the task:
echo    View:   schtasks /query /tn "GlobesDailySummary"
echo    Run:    schtasks /run  /tn "GlobesDailySummary"
echo    Delete: schtasks /delete /tn "GlobesDailySummary" /f
echo.
pause
