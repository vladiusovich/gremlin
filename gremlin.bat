@echo off
setlocal EnableExtensions
rem Single entry point: routes "gremlin <command> [options]" to the scripts in commands\.
rem
rem   gremlin run [options]            proxy (if not running yet) + browser (commands\run.bat)
rem   gremlin proxy run [options]      proxy only, in the current console (commands\proxy-run.bat)
rem   gremlin browser run [options]    browser only, the proxy must be running (commands\run.bat --no-proxy-start)
rem   gremlin phone run [options]      proxy + WireGuard for phones, in mitmweb (commands\proxy-run.bat -g -w)
rem   gremlin install                 install mitmproxy and trust its certificate (install.bat)
rem   gremlin test [pytest options]    run the tests (run_tests.bat)
rem
rem The options after the command are passed on unchanged.

set "ROOT=%~dp0"
set "TARGET="
set "ARGS="
set "GROUP=%~1"
set "CMD=%~2"

if /i "%GROUP%"=="proxy"   if /i "%CMD%"=="run" set "TARGET=commands\proxy-run.bat"
if /i "%GROUP%"=="browser" if /i "%CMD%"=="run" (set "TARGET=commands\run.bat" & set "ARGS= --no-proxy-start")
if /i "%GROUP%"=="phone"   if /i "%CMD%"=="run" (set "TARGET=commands\proxy-run.bat" & set "ARGS= --wireguard --web")
if defined TARGET (shift & shift & goto :collect)
if /i "%GROUP%"=="run"     (set "TARGET=commands\run.bat" & shift & goto :collect)
if /i "%GROUP%"=="install" (set "TARGET=install.bat" & shift & goto :collect)
if /i "%GROUP%"=="test"    (set "TARGET=run_tests.bat" & shift & goto :collect)
if "%GROUP%"=="" goto :help
if /i "%GROUP%"=="help"   goto :help
if /i "%GROUP%"=="-h"     goto :help
if /i "%GROUP%"=="--help" goto :help
echo [!!] Unknown command: gremlin %*
goto :help

:collect
rem %* ignores shift, so rebuild the rest of the arguments one by one (quotes kept as typed)
if [%1]==[] goto :run
set ARGS=%ARGS% %1
shift
goto :collect

:run
rem No `call`: control passes to the target, which avoids a second expansion of % in arguments
rem (e.g. %20 in a URL), and its exit code becomes gremlin's exit code
"%ROOT%%TARGET%"%ARGS%

:help
echo Usage:
echo   gremlin run         [URL] [-e profile] [-b chrome^|edge^|path] [-p PORT] [-r rules.json] [-w] [-k] [--dry-run]
echo                       proxy (if not running yet) + browser
echo   gremlin proxy run   [-e profile] [-p PORT] [-r rules.json] [-w] [-g] [--wg-port PORT] [--dry-run]
echo                       proxy only, in this console; -g adds WireGuard for phones
echo   gremlin phone run   [-e profile] [-p PORT] [-r rules.json] [--wg-port PORT] [--dry-run]
echo                       proxy + WireGuard for phones, QR code in mitmweb
echo   gremlin browser run [URL] [-e profile] [-b chrome^|edge^|path] [-p PORT] [-k] [--dry-run]
echo                       browser only, the proxy must already be running
echo   gremlin install
echo   gremlin test        [pytest options]
exit /b 1
