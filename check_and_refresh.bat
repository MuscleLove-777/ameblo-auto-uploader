@echo off
setlocal
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=C:\Users\atsus\AppData\Local\Python\pythoncore-3.14-64\python.exe"
cd /d "%~dp0"
"%PYTHON_EXE%" "%~dp0auth_refresh_job.py" >> "%~dp0auth_refresh_run.log" 2>&1
exit /b %ERRORLEVEL%
