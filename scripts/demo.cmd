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
"%PY%" "%CD%\scripts\demo.py" %*
if errorlevel 1 exit /b 1
echo.
echo Rules close unambiguous loops. An LLM may investigate leftovers if a key is set. Pass --no-llm for rules only.
echo Dashboard: cd dashboard ^&^& npm install ^&^& npm run dev
exit /b 0
