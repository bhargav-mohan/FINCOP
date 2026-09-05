@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else if exist ".venv\bin\python" (
  set "PY=.venv\bin\python"
) else (
  set "PY=python"
)

set "PYTHONPATH=%CD%\src"
echo == tests ==
"%PY%" -m pytest tests -q --tb=line
if errorlevel 1 exit /b 1

echo.
echo == published figures ==
"%PY%" "%CD%\scripts\verify.py"
if errorlevel 1 exit /b 1

echo.
echo ok  verify
exit /b 0
