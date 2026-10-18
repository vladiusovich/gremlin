@echo off
setlocal EnableExtensions
rem Single entry point on Windows: runs "gremlin <command> [options]" with Python (lib\main.py).
rem
rem   gremlin browser run [options]    proxy (if not running yet) + browser
rem   gremlin proxy run [options]      proxy only, in the current console
rem   gremlin mobile run [options]     proxy + WireGuard for phones, in mitmweb
rem   gremlin install [-y]             Python, mitmproxy and its certificate (install.bat)
rem   gremlin test [pytest options]    run the tests
rem
rem The options after the command are passed on unchanged.

set "ROOT=%~dp0"
rem install works without Python: install.bat sets it up first
if /i "%~1"=="install" goto :install

call "%ROOT%lib\find-python.bat"
if not defined PYTHON (
  echo [!!] Python 3.10+ not found. Run: install.bat
  exit /b 1
)
rem No `call`: it would expand % in arguments a second time (e.g. %20 in a URL)
"%PYTHON%" "%ROOT%lib\main.py" %*
exit /b %errorlevel%

:install
rem %* ignores shift, so rebuild the rest of the arguments one by one (quotes kept as typed)
shift
set "ARGS="
:collect
if [%1]==[] goto :run_install
set ARGS=%ARGS% %1
shift
goto :collect
:run_install
"%ROOT%install.bat"%ARGS%
