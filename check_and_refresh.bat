@echo off
REM ============================================================
REM Ameblo Cookie Refresh - age guard wrapper
REM Runs auto_refresh_cookies.py only if .last_refresh is older
REM than MAX_DAYS days (or missing entirely).
REM Triggered by Task Scheduler (daily + on logon).
REM ============================================================
setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
set LAST_FILE=%SCRIPT_DIR%.last_refresh
set LOG_FILE=%SCRIPT_DIR%refresh.log
set LOCK_FILE=%SCRIPT_DIR%.refresh.lock
set MAX_DAYS=1
set LOCK_STALE_HOURS=2
set PYTHON_EXE=C:\Users\atsus\AppData\Local\Python\pythoncore-3.14-64\python.exe

REM --- concurrency guard: clear a stale lock left by an interrupted run ---
if exist "%LOCK_FILE%" (
    for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[int]((Get-Date) - (Get-Item '%LOCK_FILE%').LastWriteTime).TotalHours"`) do set LOCK_AGE_HOURS=%%i
    if !LOCK_AGE_HOURS! GEQ %LOCK_STALE_HOURS% (
        echo [%date% %time%] stale lock detected ^(!LOCK_AGE_HOURS!h old^), removing >> "%LOG_FILE%"
        del "%LOCK_FILE%"
    ) else (
        echo [%date% %time%] another refresh in progress, skipping ^(lock age !LOCK_AGE_HOURS!h^) >> "%LOG_FILE%"
        exit /b 0
    )
)
echo %date% %time% > "%LOCK_FILE%"

REM --- timestamp for log ---
for /f "tokens=1-3 delims=/:. " %%a in ("%date% %time%") do set STAMP=%%a-%%b-%%c

REM --- compute age in days ---
if exist "%LAST_FILE%" (
    for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "[int]((Get-Date) - (Get-Item '%LAST_FILE%').LastWriteTime).TotalDays"`) do set AGE=%%i
) else (
    set AGE=999
)

echo [%date% %time%] check_and_refresh: age=!AGE! days, threshold=%MAX_DAYS% >> "%LOG_FILE%"

if !AGE! LSS %MAX_DAYS% (
    echo [%date% %time%] Skipping - cookie fresh ^(!AGE! days old^) >> "%LOG_FILE%"
    if exist "%LOCK_FILE%" del "%LOCK_FILE%"
    exit /b 0
)

echo [%date% %time%] Running auto_refresh_cookies.py ^(age=!AGE! ^>= %MAX_DAYS%^) >> "%LOG_FILE%"
cd /d "%SCRIPT_DIR%"
"%PYTHON_EXE%" auto_refresh_cookies.py >> "%LOG_FILE%" 2>&1
set RC=!ERRORLEVEL!
echo [%date% %time%] auto_refresh_cookies.py exited with rc=!RC! >> "%LOG_FILE%"
if exist "%LOCK_FILE%" del "%LOCK_FILE%"
exit /b !RC!
