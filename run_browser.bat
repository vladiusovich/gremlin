@echo off
setlocal EnableExtensions
rem Opens a browser with a dedicated profile whose traffic all goes through mitmproxy.
rem If no proxy is listening on the port yet, runs start_proxy.bat in a separate window.
rem
rem   run_browser.bat [URL] [options]
rem
rem   URL                    start page (default http://localhost:3001/)
rem   -e, --env NAME         settings profile env\NAME.env (default env\default.env, if present)
rem   -b, --browser NAME     chrome | edge | path to a Chromium-based browser exe (default chrome)
rem   -p, --port PORT        proxy port (default 8080)
rem   -r, --rules FILE       rules file for mock_errors.py (default rules\rules.json)
rem   -w, --web              start the proxy as mitmweb (traffic UI at http://127.0.0.1:8081)
rem   -k, --insecure         ignore certificate errors (if install.bat was not run)
rem   --no-proxy-start       do not start the proxy, browser only
rem   --dry-run              print the commands without running anything
rem
rem Priority: command line > profile > built-in default.
rem
rem Examples:
rem   run_browser.bat
rem   run_browser.bat -e staging
rem   run_browser.bat https://app.example.com/ -b edge -p 8081

set "ROOT=%~dp0"
set "ENV_NAME="
set "OPT_URL="
set "OPT_BROWSER="
set "OPT_PORT="
set "OPT_RULES="
set "OPT_WEB="
set "OPT_INSECURE="
set "START_PROXY=1"
set "DRY="

:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="-e"               (set "ENV_NAME=%~2" & shift & shift & goto :parse)
if /i "%~1"=="--env"            (set "ENV_NAME=%~2" & shift & shift & goto :parse)
if /i "%~1"=="-b"               (set "OPT_BROWSER=%~2" & shift & shift & goto :parse)
if /i "%~1"=="--browser"        (set "OPT_BROWSER=%~2" & shift & shift & goto :parse)
if /i "%~1"=="-p"               (set "OPT_PORT=%~2" & shift & shift & goto :parse)
if /i "%~1"=="--port"           (set "OPT_PORT=%~2" & shift & shift & goto :parse)
if /i "%~1"=="-r"               (set "OPT_RULES=%~f2" & shift & shift & goto :parse)
if /i "%~1"=="--rules"          (set "OPT_RULES=%~f2" & shift & shift & goto :parse)
if /i "%~1"=="-w"               (set "OPT_WEB=1" & shift & goto :parse)
if /i "%~1"=="--web"            (set "OPT_WEB=1" & shift & goto :parse)
if /i "%~1"=="-k"               (set "OPT_INSECURE=1" & shift & goto :parse)
if /i "%~1"=="--insecure"       (set "OPT_INSECURE=1" & shift & goto :parse)
if /i "%~1"=="--no-proxy-start" (set "START_PROXY=" & shift & goto :parse)
if /i "%~1"=="--dry-run"        (set "DRY=1" & shift & goto :parse)
if /i "%~1"=="-h"               goto :help
if /i "%~1"=="--help"           goto :help
set "ARG=%~1"
if "%ARG:~0,1%"=="-" (
  echo [!!] Unknown option: %~1
  goto :help
)
set "OPT_URL=%~1"
shift
goto :parse
:parsed

call "%ROOT%lib\load-env.bat" "%ENV_NAME%" || exit /b 1
if defined ENV_FILE echo [ok] Profile: %ENV_FILE%

set "URL=http://localhost:3001/"
if defined MITM_URL set "URL=%MITM_URL%"
if defined OPT_URL set "URL=%OPT_URL%"
set "BROWSER=chrome"
if defined MITM_BROWSER set "BROWSER=%MITM_BROWSER%"
if defined OPT_BROWSER set "BROWSER=%OPT_BROWSER%"
set "PORT=8080"
if defined MITM_PORT set "PORT=%MITM_PORT%"
if defined OPT_PORT set "PORT=%OPT_PORT%"
set "RULES=%ROOT%rules\rules.json"
if defined MITM_RULES set "RULES=%MITM_RULES%"
if defined OPT_RULES set "RULES=%OPT_RULES%"
set "PROXY_FLAGS="
call :is_on "%MITM_WEB%" && set "PROXY_FLAGS=--web"
if defined OPT_WEB set "PROXY_FLAGS=--web"
set "EXTRA="
call :is_on "%MITM_INSECURE%" && set "EXTRA=--ignore-certificate-errors"
if defined OPT_INSECURE set "EXTRA=--ignore-certificate-errors"
rem Pass the profile on, so start_proxy.bat resolves its own settings the same way
set "ENV_ARG="
if defined ENV_NAME set ENV_ARG=-e "%ENV_NAME%"

call "%ROOT%lib\validate.bat" port "%PORT%" || exit /b 1
call "%ROOT%lib\validate.bat" bool MITM_WEB "%MITM_WEB%" || exit /b 1
call "%ROOT%lib\validate.bat" bool MITM_INSECURE "%MITM_INSECURE%" || exit /b 1
if /i not "%URL:~0,7%"=="http://" if /i not "%URL:~0,8%"=="https://" (
  echo [!!] Invalid URL "%URL%": must start with http:// or https:// ^(URL argument or MITM_URL in the profile^)
  exit /b 1
)

if /i "%BROWSER%"=="chrome" (set "EXE=chrome") else if /i "%BROWSER%"=="edge" (set "EXE=msedge") else (set "EXE=%BROWSER%")
rem chrome/edge are resolved by Windows via App Paths; anything else must be an existing exe or on PATH
if /i not "%BROWSER%"=="chrome" if /i not "%BROWSER%"=="edge" if not exist "%EXE%" (
  where "%EXE%" >nul 2>nul || (
    echo [!!] Browser "%BROWSER%" not found: use chrome, edge or a full path to the exe ^(option -b or MITM_BROWSER in the profile^)
    exit /b 1
  )
)
rem Separate profile per browser+port pair: otherwise the flags are ignored if the browser is already open
for %%n in ("%BROWSER%") do set "PROFILE_DIR=%TEMP%\mitm-profile-%%~nn-%PORT%"

if not defined START_PROXY goto :browser
call :is_listening
if not errorlevel 1 (
  echo [ok] Proxy is already listening on port %PORT%.
  goto :browser
)

if defined DRY (
  call "%ROOT%start_proxy.bat" %ENV_ARG% -p %PORT% -r "%RULES%" %PROXY_FLAGS% --dry-run || exit /b 1
  goto :browser
)
rem Fail here with a clear message instead of in a window that closes right away
call "%ROOT%lib\find-mitmdump.bat"
if not defined MITMDUMP (
  echo [!!] mitmdump not found. Run install.bat
  exit /b 1
)
echo [..] Starting the proxy in a separate window "mitmproxy :%PORT%"
rem cmd /k keeps the window open, so startup errors stay visible
start "mitmproxy :%PORT%" cmd /k ""%ROOT%start_proxy.bat" %ENV_ARG% -p %PORT% -r "%RULES%" %PROXY_FLAGS%"

for /l %%i in (1,1,30) do (
  call :is_listening && goto :browser
  timeout /t 1 /nobreak >nul
)
echo [!!] The proxy did not start within 30 seconds, see the "mitmproxy :%PORT%" window.
exit /b 1

:browser
echo [..] Opening %BROWSER% -^> "%URL%"
if defined DRY (
  echo      %EXE% --user-data-dir="%PROFILE_DIR%" --proxy-server=127.0.0.1:%PORT% --proxy-bypass-list="<-loopback>" --disable-quic --no-first-run --no-default-browser-check %EXTRA% "%URL%"
  exit /b 0
)
rem <-loopback> removes the built-in localhost bypass, --disable-quic keeps HTTP/3 from skipping the proxy
start "" "%EXE%" --user-data-dir="%PROFILE_DIR%" --proxy-server=127.0.0.1:%PORT% --proxy-bypass-list="<-loopback>" --disable-quic --no-first-run --no-default-browser-check %EXTRA% "%URL%"
if errorlevel 1 (
  echo [!!] Failed to start "%EXE%". Specify the full path: -b "C:\...\browser.exe"
  exit /b 1
)
exit /b 0

:is_listening
powershell -NoProfile -Command "$c = New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', %PORT%); exit 0 } catch { exit 1 } finally { $c.Close() }"
exit /b %errorlevel%

:is_on
for %%v in (1 true yes on) do if /i "%~1"=="%%v" exit /b 0
exit /b 1

:help
echo Usage: run_browser.bat [URL] [-e profile] [-b chrome^|edge^|path] [-p PORT] [-r rules.json] [-w] [-k] [--no-proxy-start] [--dry-run]
exit /b 1
