@echo off
rem Finds Python 3.10+ and stores its full path in PYTHON (empty if not found).
rem Invoked via `call` from gremlin.bat and install.bat, hence no setlocal.
set "PYTHON="
rem "python" may be the Microsoft Store stub: it fails the probe and is skipped
for %%c in (python py) do if not defined PYTHON call :probe %%c
rem Installed a moment ago by install.bat: PATH in this console is stale
for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if not defined PYTHON call :probe "%%~d\python.exe"
exit /b 0

:probe
rem `call` keeps cmd from stripping the quotes around a path with spaces
for /f "delims=" %%i in ('call %1 -c "import sys; sys.version_info >= (3, 10) and print(sys.executable)" 2^>nul') do set "PYTHON=%%i"
exit /b 0
