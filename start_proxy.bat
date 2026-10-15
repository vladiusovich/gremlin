@echo off
setlocal EnableExtensions
rem Starts mitmproxy in the current console with every addon from addons\ loaded.
rem Stop with Ctrl+C.
rem
rem   start_proxy.bat [options]
rem
rem   -e, --env NAME         settings profile env\NAME.env (default env\default.env, if present)
rem   -p, --port PORT        listen port (default 8080)
rem   -r, --rules FILE       rules file for mock_errors.py (default rules\rules.json)
rem   -w, --web              use mitmweb (traffic UI at http://127.0.0.1:8081) instead of mitmdump
rem   --dry-run              print the command without running it
rem
rem Priority: command line > profile > built-in default.
rem Addons: every addons\*.py is loaded; files starting with "_" are skipped (shared helpers).

set "ROOT=%~dp0"
set "ENV_NAME="
set "OPT_PORT="
set "OPT_RULES="
set "OPT_WEB="
set "DRY="

:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="-e"        (set "ENV_NAME=%~2" & shift & shift & goto :parse)
if /i "%~1"=="--env"     (set "ENV_NAME=%~2" & shift & shift & goto :parse)
if /i "%~1"=="-p"        (set "OPT_PORT=%~2" & shift & shift & goto :parse)
if /i "%~1"=="--port"    (set "OPT_PORT=%~2" & shift & shift & goto :parse)
if /i "%~1"=="-r"        (set "OPT_RULES=%~f2" & shift & shift & goto :parse)
if /i "%~1"=="--rules"   (set "OPT_RULES=%~f2" & shift & shift & goto :parse)
if /i "%~1"=="-w"        (set "OPT_WEB=1" & shift & goto :parse)
if /i "%~1"=="--web"     (set "OPT_WEB=1" & shift & goto :parse)
if /i "%~1"=="--dry-run" (set "DRY=1" & shift & goto :parse)
echo [!!] Unknown option: %~1
echo Usage: start_proxy.bat [-e profile] [-p PORT] [-r rules.json] [-w] [--dry-run]
exit /b 1
:parsed

call "%ROOT%lib\load-env.bat" "%ENV_NAME%" || exit /b 1
if defined ENV_FILE echo [ok] Profile: %ENV_FILE%

set "PORT=8080"
if defined MITM_PORT set "PORT=%MITM_PORT%"
if defined OPT_PORT set "PORT=%OPT_PORT%"
set "RULES=%ROOT%rules\rules.json"
if defined MITM_RULES set "RULES=%MITM_RULES%"
if defined OPT_RULES set "RULES=%OPT_RULES%"
set "WEB="
call :is_on "%MITM_WEB%" && set "WEB=1"
if defined OPT_WEB set "WEB=1"

call "%ROOT%lib\validate.bat" port "%PORT%" || exit /b 1
call "%ROOT%lib\validate.bat" bool MITM_WEB "%MITM_WEB%" || exit /b 1

call "%ROOT%lib\find-mitmdump.bat"
if not defined MITMDUMP (
  echo [!!] mitmdump not found. Run install.bat
  exit /b 1
)
set "TOOL=%MITMDUMP%"
rem mitmweb.exe ships next to mitmdump.exe
if defined WEB for %%i in ("%MITMDUMP%") do set "TOOL=%%~dpimitmweb.exe"

if exist "%RULES%" goto :rules_ok
if /i not "%RULES%"=="%ROOT%rules\rules.json" (
  echo [!!] Rules file not found: %RULES%
  exit /b 1
)
rem The default rules file is personal and not in git: start with an empty rule set
if defined DRY (
  echo [..] An empty rules\rules.json would be created
) else (
  > "%RULES%" echo []
  echo [ok] Created an empty rules\rules.json, example rules: rules\examples.json
)
:rules_ok

set "ADDONS="
for %%a in ("%ROOT%addons\*.py") do call :add_addon "%%~fa"

echo [..] Proxy 127.0.0.1:%PORT%, rules: %RULES%
if defined DRY (
  echo      "%TOOL%" -p %PORT%%ADDONS% --set "rules_file=%RULES%"
  exit /b 0
)
title mitmproxy :%PORT%
"%TOOL%" -p %PORT%%ADDONS% --set "rules_file=%RULES%"
exit /b %errorlevel%

:add_addon
set "NAME=%~n1"
if "%NAME:~0,1%"=="_" exit /b 0
set ADDONS=%ADDONS% -s "%~1"
exit /b 0

:is_on
for %%v in (1 true yes on) do if /i "%~1"=="%%v" exit /b 0
exit /b 1
