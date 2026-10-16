@echo off
setlocal EnableExtensions
rem Runs the test suite in a local virtualenv (.venv), creating it on first run.
rem
rem   run_tests.bat [pytest options]
rem
rem Examples:
rem   run_tests.bat                 all tests
rem   run_tests.bat -m "not e2e"    fast tests only (no real mitmdump)
rem   run_tests.bat -k cors -v      tests with "cors" in the name

set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if exist "%PY%" goto :deps
where python >nul 2>nul || (
  echo [!!] Python not found. Install Python 3.10+ from https://www.python.org/downloads/
  exit /b 1
)
echo [..] Creating .venv...
python -m venv "%ROOT%.venv" || exit /b 1

:deps
rem Reinstall only when requirements-dev.txt is newer than the marker
set "MARKER=%ROOT%.venv\.deps-installed"
if exist "%MARKER%" (
  for /f %%i in ('powershell -NoProfile -Command "if ((Get-Item '%ROOT%requirements-dev.txt').LastWriteTime -gt (Get-Item '%MARKER%').LastWriteTime) { 'stale' }"') do del "%MARKER%"
)
if not exist "%MARKER%" (
  echo [..] Installing test dependencies...
  "%PY%" -m pip install -q --disable-pip-version-check -r "%ROOT%requirements-dev.txt" || exit /b 1
  > "%MARKER%" echo ok
)

pushd "%ROOT%"
"%PY%" -m pytest %*
set "CODE=%errorlevel%"
popd
exit /b %CODE%
